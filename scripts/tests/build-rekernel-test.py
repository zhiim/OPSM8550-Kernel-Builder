"""Check the contract between Kernel Builder and ReKernel-X without building a kernel."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "build-rekernel.sh"


class ReKernelIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rekernel-integration-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "sm8550/out"
        (self.out / "include/config").mkdir(parents=True)
        (self.out / "include/config/kernel.release").write_text("5.15.220-gfixture\n")
        (self.out / "arch/arm64/boot").mkdir(parents=True)
        (self.out / "arch/arm64/boot/Image").write_bytes(b"fixture kernel image")
        self.module = self.root / "rekernel-source"
        (self.module / "scripts").mkdir(parents=True)
        self.fixture = self.module / "scripts/build-custom-lkm.sh"
        self.fixture.write_text("""#!/usr/bin/env bash
set -euo pipefail
printf 'release=%s\\nversion=%s\\nflags=%s\\n' "$EXPECTED_KERNEL_RELEASE" "$RKX_VERSION" "${KERNEL_MAKE_FLAGS:-}"
printf 'arg=%s\\n' "$@"
if [[ ${FIXTURE_FAIL:-0} != 0 ]]; then exit "$FIXTURE_FAIL"; fi
printf 'fixture only' > "$4/fixture-module.zip"
""")
        # Real git metadata is used only to record the checked-out module commit.
        subprocess.run(["git", "init", "-q", str(self.module)], check=True)
        subprocess.run(["git", "-C", str(self.module), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.module),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            check=True,
        )
        self.summary = self.root / "summary.md"
        self.env = dict(
            os.environ,
            GITHUB_WORKSPACE=str(self.root),
            SOC="sm8550",
            CLANG_VERSION="clang-r596125",
            KSU_TYPE="KernelSU-Next-with-susfs-nomount",
            GITHUB_RUN_NUMBER="123",
            GITHUB_RUN_ATTEMPT="2",
            GITHUB_RUN_ID="456",
            GITHUB_REPOSITORY="zhiim/OPSM8550-Kernel-Builder",
            GITHUB_STEP_SUMMARY=str(self.summary),
            KERNEL_COMMIT="fixture-base-commit",
            KERNEL_MAKE_FLAGS="CONFIG_OPLUS_DEVICE_DTBS=y CONFIG_SALAMI_DTB=y CONFIG_ASTON_DTB=y",
        )
        self.dest = self.root / "rekernel-output"

    def run_script(self):
        return subprocess.run(
            ["bash", str(SCRIPT)],
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def test_passes_this_jobs_build_inputs_and_records_pairing(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        log = (self.dest / "build.log").read_text()
        self.assertIn("release=5.15.220-gfixture", log)
        self.assertIn("version=custom-r123.2-KernelSU-Next-with-susfs-nomount", log)
        self.assertIn("flags=" + self.env["KERNEL_MAKE_FLAGS"], log)
        self.assertIn(f"arg={self.out}", log)
        self.assertIn(f"arg={self.root}/toolchains/clang-r596125/bin", log)
        pairing = (self.dest / "pairing-info.txt").read_text()
        self.assertIn("actions/runs/456", pairing)
        self.assertIn("kernel_image_sha256=", pairing)
        self.assertIn("fixture-base-commit", pairing)
        subprocess.run(
            ["sha256sum", "--check", "SHA256SUMS"],
            cwd=self.dest,
            check=True,
            capture_output=True,
        )
        self.assertIn("5.15.220-gfixture", self.summary.read_text())

    def test_module_failure_propagates_and_keeps_log(self):
        self.env["FIXTURE_FAIL"] = "23"
        result = self.run_script()
        self.assertEqual(result.returncode, 23, result.stdout)
        self.assertTrue((self.dest / "build.log").is_file())
        self.assertFalse((self.dest / "pairing-info.txt").exists())
        self.assertFalse((self.dest / "SHA256SUMS").exists())

    def test_missing_kernel_output_fails_before_module_build(self):
        (self.out / "include/config/kernel.release").unlink()
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing include/config/kernel.release", result.stdout)
        self.assertFalse(list(self.dest.glob("*.zip")))

    def test_old_module_revision_fails_with_actionable_error(self):
        self.fixture.unlink()
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not contain build-custom-lkm.sh", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
