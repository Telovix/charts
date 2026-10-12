"""Render-only qualification; these tests do not deploy published Sensor images."""

from pathlib import Path
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
            "/usr/local/bin/telovix-sensor", "--capture-owner-readiness",
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

    def test_worker_digest_resources_and_pull_policy_do_not_roll_owner(self):
        before = daemonsets(render())
        after = daemonsets(render(
            "image.digest=sha256:" + "c" * 64,
            "image.pullPolicy=IfNotPresent",
            "captureDelivery.worker.resources.requests.memory=96Mi",
        ))
        self.assertEqual(before["test-telovix-sensor"]["spec"], after["test-telovix-sensor"]["spec"])
        self.assertNotEqual(before["test-telovix-sensor-delivery"]["spec"], after["test-telovix-sensor-delivery"]["spec"])

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
        self.assertNotIn("rm -", init)
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
            ("upgradeController.enabled=true",),
        ):
            with self.subTest(settings=settings):
                self.assertNotEqual(render(*settings).returncode, 0)
        result = render(
            "sensor.consoleUrl=https://console.example.invalid",
            "sensor.enrollmentToken=test-token",
            "clusterName=test-cluster",
            "upgradeController.enabled=true",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("captureDelivery requires upgradeController.enabled=false", result.stderr)

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
