"""Render-only qualification; these tests do not deploy published Sensor images."""

from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

import yaml


CHART = Path(__file__).resolve().parents[1] / "telovix-sensor"
OWNER_IMAGE = "registry.gitlab.com/telovix/sensor@sha256:" + "a" * 64


def render(*settings, split=True, chart=CHART):
    command = ["helm", "template", "test", str(chart), "--namespace", "telovix-system"]
    if split:
        settings = (
            "captureDelivery.enabled=true",
            "captureDelivery.ownerImage=" + OWNER_IMAGE,
            *settings,
        )
    for setting in settings:
        flag = "--set" if setting.endswith(("=true", "=false")) else "--set-string"
        command.extend((flag, setting))
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result


def manifests(result):
    if result.returncode:
        raise AssertionError(result.stderr)
    return list(yaml.safe_load_all(result.stdout))


def daemonsets(result):
    return {
        document["metadata"]["name"]: document
        for document in manifests(result)
        if document["kind"] == "DaemonSet"
    }


class CaptureDeliveryTests(unittest.TestCase):
    def test_owner_teardown_has_time_to_drain_and_retire_capture_resources(self):
        for daemonset in daemonsets(render()).values():
            self.assertEqual(daemonset['spec']['template']['spec']['terminationGracePeriodSeconds'], 90)

    def test_owner_bootstrap_is_atomic_and_preserves_installation_recovery(self):
        owner = daemonsets(render())["test-telovix-sensor"]
        spec = owner["spec"]["template"]["spec"]
        self.assertEqual(spec["containers"][0]["command"], [
            "/usr/bin/tini", "--", "/var/lib/telovix-sensor/capture-owner-bin/telovix-sensor"])
        script = spec["initContainers"][0]["command"][-1]
        with tempfile.TemporaryDirectory(prefix="telovix-owner-bootstrap-") as directory:
            root = Path(directory)
            state = root / "state"
            state.mkdir()
            source = root / "image-sensor"
            def owner_image(version, label, protocol=8, handoff=15):
                contract = json.dumps(dict(architecture="fixture", component="capture-owner",
                    delivery_protocol_version=protocol, engine_version="v1.7.1", flavor="telecom",
                    handoff_version=handoff, installation_version=1, version=version), separators=(",", ":"))
                return ("#!/bin/sh\nprintf '%s\\n' '" + contract + "'\n# " + label + "\n").encode()
            source.write_bytes(owner_image("1.0.77", "initial owner image"))
            source.chmod(0o555)
            script = script.replace("/sensor-state", str(state)).replace(
                "/usr/local/bin/telovix-sensor", str(source))
            def bootstrap():
                return subprocess.run(["/bin/sh", "-c", "mountpoint() { return 0; };\n" + script],
                                      capture_output=True, text=True, check=False)
            self.assertEqual(bootstrap().returncode, 0)
            installed = state / "capture-owner-bin" / "telovix-sensor"
            self.assertEqual(installed.read_bytes(), source.read_bytes())
            self.assertEqual(installed.stat().st_mode & 0o777, 0o555)
            self.assertEqual(list(installed.parent.glob(".bootstrap.*")), [])
            # A completed handoff removes its recovery journal, not its installed owner.
            installed.unlink()
            committed_image = owner_image("1.0.78", "committed handed-off owner")
            installed.write_bytes(committed_image)
            installed.chmod(0o555)
            committed_inode = installed.stat().st_ino
            self.assertEqual(bootstrap().returncode, 0)
            self.assertEqual(installed.read_bytes(), committed_image)
            self.assertEqual(installed.stat().st_ino, committed_inode)
            installed.chmod(0o755)
            self.assertNotEqual(bootstrap().returncode, 0)
            self.assertEqual(installed.read_bytes(), committed_image)
            installed.chmod(0o555)
            installed.unlink()
            pending_image = owner_image("1.0.78", "pending installed candidate")
            installed.write_bytes(pending_image)
            installed.chmod(0o555)
            journal = state / ".capture-owner-install.json"
            journal.write_text("pending recovery evidence")
            source.unlink()
            desired_image = owner_image("1.0.79", "different desired image")
            source.write_bytes(desired_image)
            source.chmod(0o555)
            self.assertEqual(bootstrap().returncode, 0)
            self.assertEqual(installed.read_bytes(), pending_image)
            self.assertEqual(journal.read_text(), "pending recovery evidence")
            for incompatible in (owner_image("1.0.78", "old IPC", protocol=7),
                                 owner_image("1.0.78", "old handoff", handoff=14)):
                installed.unlink()
                installed.write_bytes(incompatible)
                installed.chmod(0o555)
                self.assertNotEqual(bootstrap().returncode, 0)
                self.assertEqual(installed.read_bytes(), incompatible)
                self.assertEqual(journal.read_text(), "pending recovery evidence")
            installed.unlink()
            self.assertNotEqual(bootstrap().returncode, 0)
            self.assertFalse(installed.exists())
            installed.symlink_to(source)
            self.assertNotEqual(bootstrap().returncode, 0)
            self.assertEqual(source.read_bytes(), desired_image)
            journal.unlink()
            self.assertNotEqual(bootstrap().returncode, 0)
            self.assertEqual(source.read_bytes(), desired_image)

    def test_split_roles_report_their_own_downward_pod_identity(self):
        expected = {"TELOVIX_POD_UID": "metadata.uid", "TELOVIX_POD_NAME": "metadata.name",
                    "TELOVIX_POD_NAMESPACE": "metadata.namespace"}
        for workload in daemonsets(render()).values():
            env = workload["spec"]["template"]["spec"]["containers"][0]["env"]
            for name, field in expected.items():
                selected = [item for item in env if item["name"] == name]
                self.assertEqual(selected, [{"name": name, "valueFrom": {"fieldRef": {"fieldPath": field}}}])
        for workload in daemonsets(render(split=False)).values():
            names = {item["name"] for item in workload["spec"]["template"]["spec"]["containers"][0]["env"]}
            self.assertFalse(names.intersection(expected))

    def test_long_controller_names_do_not_collide_with_sensor_resources(self):
        documents = manifests(render(
            "fullnameOverride=" + "a" * 63, "upgradeController.enabled=true",
            "sensor.consoleUrl=https://console.example.test", "clusterName=qualification", split=False))
        identities = [(item["apiVersion"], item["kind"], item["metadata"].get("namespace", ""),
                       item["metadata"]["name"]) for item in documents]
        self.assertEqual(len(identities), len(set(identities)))
        controller = next(item for item in documents if item["kind"] == "Deployment")
        self.assertTrue(controller["metadata"]["name"].endswith("-updater"))
        self.assertLessEqual(len(controller["metadata"]["name"]), 63)

    def test_controller_identity_is_runtime_owned_not_part_of_helm_rollback(self):
        for mode in ("managed", "flux", "argocd"):
            documents = manifests(render(
                "upgradeController.enabled=true", "upgradeController.managementMode=" + mode,
                "sensor.consoleUrl=https://console.example.test", "clusterName=qualification",
                split=False,
            ))
            deployment = next(item for item in documents if item["kind"] == "Deployment")
            self.assertEqual(deployment["metadata"]["labels"]["telovix.com/release-name"], "test")
            env = {item["name"]: item.get("value") for item in
                   deployment["spec"]["template"]["spec"]["containers"][0]["env"]}
            identity = env["TELOVIX_UPDATER_IDENTITY_SECRET"]
            self.assertFalse(any(item["kind"] == "Secret" and item["metadata"]["name"] == identity
                                 for item in documents))
            self.assertEqual(env["TELOVIX_UPDATER_CONTROLLER_WORKLOAD"], deployment["metadata"]["name"])
            role = next(item for item in documents if item["kind"] == "Role"
                        and item["metadata"]["name"] == deployment["metadata"]["name"])
            self.assertTrue(any(rule["apiGroups"] == [""] and rule["resources"] == ["secrets"]
                                and rule["verbs"] == ["create"] and "resourceNames" not in rule
                                for rule in role["rules"]))
            self.assertTrue(any(rule["apiGroups"] == ["apps"] and rule["resources"] == ["deployments"]
                                and rule.get("resourceNames") == [deployment["metadata"]["name"]]
                                and rule["verbs"] == ["get"] for rule in role["rules"]))

    def test_managed_controller_can_watch_owner_resources_without_sensor_rbac(self):
        for mode in ("managed", "flux", "argocd"):
            documents = manifests(render(
                "upgradeController.enabled=true", "upgradeController.managementMode=" + mode,
                "sensor.consoleUrl=https://console.example.test", "clusterName=qualification",
                "rbac.create=false", "rbac.clusterWide=false", split=False,
            ))
            role = next(item for item in documents if item["kind"] == "Role"
                        and item["metadata"]["name"].endswith("-updater"))
            self.assertEqual(role["metadata"]["namespace"], "telovix-system")
            watched = {(group, resource) for rule in role["rules"] if "watch" in rule["verbs"]
                       for group in rule["apiGroups"] for resource in rule["resources"]}
            expected = {
                ("", "configmaps"), ("", "secrets"), ("", "serviceaccounts"),
                ("", "pods"), ("apps", "daemonsets")} if mode == "managed" else set()
            self.assertEqual(watched, expected)

    def test_controller_uses_exact_workload_names_for_observation(self):
        for name in ("custom-owner", "a" * 63):
            documents = manifests(render(
                "fullnameOverride=" + name,
                "upgradeController.enabled=true",
                "sensor.consoleUrl=https://console.example.test",
                "clusterName=qualification",
                split=False,
            ))
            controller = next(document for document in documents
                              if document["kind"] == "Deployment")
            env = {item["name"]: item.get("value") for item in
                   controller["spec"]["template"]["spec"]["containers"][0]["env"]}
            self.assertEqual(env["TELOVIX_UPDATER_CAPTURE_WORKLOAD"], name)
            self.assertEqual(env["TELOVIX_UPDATER_DELIVERY_WORKLOAD"],
                             name[:54].rstrip("-") + "-delivery")

    def test_only_managed_controller_can_persist_job_results(self):
        for mode in ("managed", "flux", "argocd"):
            documents = manifests(render(
                "upgradeController.enabled=true",
                "upgradeController.managementMode=" + mode,
                "sensor.consoleUrl=https://console.example.test",
                "clusterName=qualification",
                split=False,
            ))
            role = next(document for document in documents
                        if document["kind"] == "Role"
                        and document["metadata"]["name"].endswith("-updater"))
            job_rules = [rule for rule in role["rules"]
                         if rule.get("apiGroups") == ["batch"]
                         and "jobs" in rule["resources"]]
            if mode == "managed":
                self.assertEqual(len(job_rules), 1)
                self.assertIn("patch", job_rules[0]["verbs"])
            else:
                self.assertEqual(job_rules, [])

    def test_split_mode_rejects_an_owner_without_host_pid_visibility(self):
        rejected = render("hostPID=false")
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("captureDelivery.enabled requires hostPID=true", rejected.stderr)
        legacy = daemonsets(render("hostPID=false", split=False))["test-telovix-sensor"]
        self.assertFalse(legacy["spec"]["template"]["spec"]["hostPID"])

    def test_split_owner_readiness_and_replacement_are_independent_of_worker(self):
        owner = daemonsets(render())["test-telovix-sensor"]
        self.assertEqual(owner["spec"]["updateStrategy"], {"type": "OnDelete"})
        container = owner["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(container["readinessProbe"]["exec"]["command"], [
            "/var/lib/telovix-sensor/capture-owner-bin/telovix-sensor", "--capture-owner-readiness",
        ])
        self.assertEqual(container["readinessProbe"]["timeoutSeconds"], 5)
        legacy = daemonsets(render(split=False))["test-telovix-sensor"]
        self.assertEqual(legacy["spec"]["updateStrategy"]["type"], "RollingUpdate")
        self.assertEqual(legacy["spec"]["template"]["spec"]["containers"][0]["readinessProbe"]["exec"]["command"], [
            "/bin/sh", "-ec", "test -s /var/lib/telovix-sensor/.sensor-ready",
        ])

    def test_worker_release_leaves_owner_template_and_spec_unchanged(self):
        before = daemonsets(render("image.tag=1.0.64"))
        after = daemonsets(render("image.tag=1.0.65"))
        self.assertEqual(set(before), {"test-telovix-sensor", "test-telovix-sensor-delivery"})
        self.assertEqual(before["test-telovix-sensor"]["spec"], after["test-telovix-sensor"]["spec"])
        worker_before = before["test-telovix-sensor-delivery"]["spec"]["template"]["spec"]
        worker_after = after["test-telovix-sensor-delivery"]["spec"]["template"]["spec"]
        self.assertNotEqual(worker_before["containers"][0]["image"], worker_after["containers"][0]["image"])
        self.assertEqual(worker_before["containers"][0]["args"], ["--delivery-worker"])
        self.assertEqual(after["test-telovix-sensor"]["spec"]["template"]["spec"]["containers"][0]["image"], OWNER_IMAGE)

    def test_same_chart_worker_digest_changes_only_the_worker_resource(self):
        settings = ("sensor.enrollmentToken=qualification-token",
                    "sensor.consoleUrl=https://console.example.test", "clusterName=qualification",
                    "networkPolicy.enabled=true")
        def resources(result):
            return {(item["apiVersion"], item["kind"], item["metadata"].get("namespace", ""),
                     item["metadata"]["name"]): item for item in manifests(result)}
        before = resources(render(*settings, "image.digest=sha256:" + "b" * 64))
        after = resources(render(*settings, "image.digest=sha256:" + "c" * 64))
        self.assertEqual(set(before), set(after))
        worker_key = ("apps/v1", "DaemonSet", "telovix-system", "test-telovix-sensor-delivery")
        worker_before = before.pop(worker_key)
        worker_after = after.pop(worker_key)
        self.assertEqual(before, after)
        worker_before["spec"]["template"]["spec"]["containers"][0]["image"] = (
            "registry.gitlab.com/telovix/sensor@sha256:" + "c" * 64)
        self.assertEqual(worker_before, worker_after)

    def test_worker_digest_resources_and_pull_policy_do_not_roll_owner(self):
        before = daemonsets(render())
        after = daemonsets(render(
            "image.digest=sha256:" + "c" * 64,
            "image.pullPolicy=IfNotPresent",
            "captureDelivery.worker.resources.requests.memory=96Mi",
        ))
        self.assertEqual(before["test-telovix-sensor"]["spec"], after["test-telovix-sensor"]["spec"])
        self.assertNotEqual(before["test-telovix-sensor-delivery"]["spec"], after["test-telovix-sensor-delivery"]["spec"])

    def test_shared_environment_reaches_delivery_with_explicit_worker_overrides(self):
        workloads = daemonsets(render(
            "extraEnv[0].name=HTTPS_PROXY", "extraEnv[0].value=http://shared-proxy:3128",
            "extraEnv[1].name=NO_PROXY", "extraEnv[1].value=localhost",
            "extraEnv[2].name=PROXY_TOKEN",
            "extraEnv[2].valueFrom.secretKeyRef.name=proxy-credentials",
            "extraEnv[2].valueFrom.secretKeyRef.key=token",
            "captureDelivery.worker.extraEnv[0].name=HTTPS_PROXY",
            "captureDelivery.worker.extraEnv[0].value=http://delivery-proxy:3128",
        ))
        owner_env = workloads["test-telovix-sensor"]["spec"]["template"]["spec"]["containers"][0]["env"]
        worker_env = workloads["test-telovix-sensor-delivery"]["spec"]["template"]["spec"]["containers"][0]["env"]
        proxies = [entry for entry in worker_env if entry["name"] == "HTTPS_PROXY"]
        self.assertEqual(proxies, [{"name": "HTTPS_PROXY", "value": "http://delivery-proxy:3128"}])
        self.assertIn({"name": "NO_PROXY", "value": "localhost"}, worker_env)
        self.assertIn({"name": "PROXY_TOKEN", "valueFrom": {
            "secretKeyRef": {"name": "proxy-credentials", "key": "token"}}}, worker_env)
        self.assertIn({"name": "HTTPS_PROXY", "value": "http://shared-proxy:3128"}, owner_env)

    def test_long_names_keep_distinct_valid_workload_names(self):
        workloads = daemonsets(render("fullnameOverride=" + "a" * 63))
        self.assertEqual(len(workloads), 2)
        for name in workloads:
            self.assertLessEqual(len(name), 63)

    def test_chart_metadata_changes_do_not_roll_owner(self):
        before = daemonsets(render())
        with tempfile.TemporaryDirectory(prefix="telovix-split-chart-") as directory:
            chart = Path(directory) / "chart"
            shutil.copytree(CHART, chart)
            metadata = yaml.safe_load((chart / "Chart.yaml").read_text())
            metadata.update(version="1.0.65", appVersion="1.0.65")
            (chart / "Chart.yaml").write_text(yaml.safe_dump(metadata))
            after = daemonsets(render(chart=chart))
        self.assertEqual(before["test-telovix-sensor"]["spec"], after["test-telovix-sensor"]["spec"])
        self.assertNotEqual(before["test-telovix-sensor-delivery"]["spec"], after["test-telovix-sensor-delivery"]["spec"])

    def test_owner_enrollment_checksum_tracks_token_without_chart_metadata(self):
        first = daemonsets(render("sensor.enrollmentToken=first-token"))["test-telovix-sensor"]
        second = daemonsets(render("sensor.enrollmentToken=second-token"))["test-telovix-sensor"]
        def checksum(owner):
            return owner["spec"]["template"]["metadata"]["annotations"]["checksum/enrollment"]
        self.assertNotEqual(checksum(first), checksum(second))
        with tempfile.TemporaryDirectory(prefix="telovix-enrollment-chart-") as directory:
            chart = Path(directory) / "chart"
            shutil.copytree(CHART, chart)
            metadata = yaml.safe_load((chart / "Chart.yaml").read_text())
            metadata.update(version="1.0.65", appVersion="1.0.65")
            (chart / "Chart.yaml").write_text(yaml.safe_dump(metadata))
            upgraded = daemonsets(render("sensor.enrollmentToken=first-token", chart=chart))["test-telovix-sensor"]
        self.assertEqual(first["spec"], upgraded["spec"])

    def test_worker_cannot_initialize_capture_or_write_owner_state(self):
        workloads = daemonsets(render())
        owner = workloads["test-telovix-sensor"]["spec"]["template"]["spec"]
        worker = workloads["test-telovix-sensor-delivery"]["spec"]["template"]["spec"]
        self.assertEqual(owner["containers"][0]["args"], ["--capture-owner"])
        init = owner["initContainers"][0]["command"][-1]
        self.assertNotIn("rm -rf", init)
        self.assertNotIn("TOKEN_HASH", init)
        self.assertFalse(worker["automountServiceAccountToken"])
        for flag in ("hostPID", "hostNetwork", "hostIPC"):
            self.assertFalse(worker[flag])
        self.assertNotIn("initContainers", worker)
        container = worker["containers"][0]
        self.assertFalse(container["securityContext"]["privileged"])
        self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
        self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(container["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertEqual(container["volumeMounts"], [{
            "name": "sensor-state", "mountPath": "/var/lib/telovix-sensor", "readOnly": True,
        }])
        self.assertEqual(worker["volumes"], [{
            "name": "sensor-state", "hostPath": {"path": "/var/lib/telovix-sensor", "type": "Directory"},
        }])
        self.assertNotIn("TELOVIX_ENROLLMENT_TOKEN", {item["name"] for item in container["env"]})
        self.assertEqual(container["readinessProbe"]["exec"]["command"], [
            "/usr/local/bin/telovix-sensor", "--delivery-worker-probe",
        ])
        self.assertGreaterEqual(container["readinessProbe"]["timeoutSeconds"], 4)
        affinity = worker["affinity"]["podAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"][0]
        self.assertEqual(affinity["labelSelector"]["matchLabels"], workloads["test-telovix-sensor"]["spec"]["selector"]["matchLabels"])
        self.assertEqual(affinity["topologyKey"], "kubernetes.io/hostname")
        self.assertEqual(workloads["test-telovix-sensor-delivery"]["spec"]["updateStrategy"]["rollingUpdate"]["maxSurge"], 0)

    def test_worker_digest_and_flavor_do_not_change_owner_pin(self):
        digest = "sha256:" + "b" * 64
        workloads = daemonsets(render("flavor=telecom", "image.telecomDigest=" + digest))
        self.assertEqual(workloads["test-telovix-sensor-delivery"]["spec"]["template"]["spec"]["containers"][0]["image"], "registry.gitlab.com/telovix/sensor@" + digest)
        self.assertEqual(workloads["test-telovix-sensor"]["spec"]["template"]["spec"]["containers"][0]["image"], OWNER_IMAGE)

    def test_pin_and_automation_guards_fail_closed(self):
        for settings in (
            ("captureDelivery.ownerImage=",),
            ("captureDelivery.ownerImage=registry.gitlab.com/telovix/sensor:latest",),
            ("upgradeController.enabled=true", "upgradeController.managementMode=flux"),
            ("upgradeController.enabled=true", "upgradeController.managementMode=argocd"),
        ):
            with self.subTest(settings=settings):
                self.assertNotEqual(render(*settings).returncode, 0)
        result = render(
            "sensor.consoleUrl=https://console.example.invalid",
            "sensor.enrollmentToken=test-token",
            "clusterName=test-cluster",
            "upgradeController.enabled=true",
            "upgradeController.managementMode=flux",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("captureDelivery automated updates require upgradeController.managementMode=managed", result.stderr)

    def test_managed_split_worker_upgrade_preserves_owner_and_controller_permissions(self):
        settings = ("upgradeController.enabled=true",
                    "upgradeController.managementMode=managed",
                    "sensor.consoleUrl=https://console.example.test",
                    "sensor.enrollmentToken=qualification-token", "clusterName=qualification")
        before = manifests(render(*settings, "image.digest=sha256:" + "b" * 64))
        after = manifests(render(*settings, "image.digest=sha256:" + "c" * 64))
        workloads_before = {item["metadata"]["name"]: item for item in before
                            if item["kind"] == "DaemonSet"}
        workloads_after = {item["metadata"]["name"]: item for item in after
                           if item["kind"] == "DaemonSet"}
        owner = "test-telovix-sensor"
        worker = owner + "-delivery"
        self.assertEqual(workloads_before[owner], workloads_after[owner])
        self.assertNotEqual(workloads_before[worker], workloads_after[worker])
        controller = next(item for item in after if item["kind"] == "Deployment")
        env = {item["name"]: item.get("value") for item in
               controller["spec"]["template"]["spec"]["containers"][0]["env"]}
        self.assertEqual(env["TELOVIX_UPDATER_CAPTURE_WORKLOAD"], owner)
        self.assertEqual(env["TELOVIX_UPDATER_DELIVERY_WORKLOAD"], worker)
        role = next(item for item in after if item["kind"] == "Role"
                    and item["metadata"]["name"] == controller["metadata"]["name"])
        self.assertTrue(any(rule["apiGroups"] == ["apps"]
                            and rule["resources"] == ["daemonsets"]
                            and rule["verbs"] == ["watch"] for rule in role["rules"]))

    def test_network_policy_covers_both_roles(self):
        documents = manifests(render("networkPolicy.enabled=true"))
        policy = next(document for document in documents if document["kind"] == "NetworkPolicy")
        selector = policy["spec"]["podSelector"]
        self.assertEqual(selector["matchLabels"], {"app.kubernetes.io/instance": "test"})
        self.assertEqual(selector["matchExpressions"][0]["values"], ["sensor", "delivery-worker"])

    def test_default_and_legacy_values_keep_single_workload(self):
        self.assertEqual(len(daemonsets(render(split=False))), 1)
        result = subprocess.run([
            "helm", "template", "test", str(CHART), "--values",
            str(CHART.parent / "tests/fixtures/sensor-legacy-reuse-values.yaml"),
        ], capture_output=True, text=True, check=False)
        self.assertEqual(len(daemonsets(result)), 1)


if __name__ == "__main__":
    unittest.main()
