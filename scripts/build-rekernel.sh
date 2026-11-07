#!/usr/bin/env bash
# Reuse the current matrix job's completed kernel build and matching toolchain.
set -euo pipefail

: "${GITHUB_WORKSPACE:?}"
: "${SOC:?}"
: "${CLANG_VERSION:?}"
: "${KSU_TYPE:?}"
: "${GITHUB_RUN_NUMBER:?}"
: "${GITHUB_RUN_ATTEMPT:?}"

KERNEL_TREE="${GITHUB_WORKSPACE}/${SOC}"
KERNEL_OUTPUT="${KERNEL_TREE}/out"
RKX_SOURCE="${GITHUB_WORKSPACE}/rekernel-source"
RKX_OUTPUT="${GITHUB_WORKSPACE}/rekernel-output"
CLANG_BIN="${GITHUB_WORKSPACE}/toolchains/${CLANG_VERSION}/bin"
mkdir -p "$RKX_OUTPUT"

build_module() {
  [[ -s "${KERNEL_OUTPUT}/include/config/kernel.release" ]] || {
    echo 'ERROR: Completed kernel build is missing include/config/kernel.release.'
    return 1
  }
  [[ -f "${RKX_SOURCE}/scripts/build-custom-lkm.sh" ]] || {
    echo 'ERROR: Selected ReKernel-X revision does not contain build-custom-lkm.sh.'
    return 1
  }

  EXPECTED_KERNEL_RELEASE="$(cat "${KERNEL_OUTPUT}/include/config/kernel.release")"
  export EXPECTED_KERNEL_RELEASE
  export RKX_VERSION="custom-r${GITHUB_RUN_NUMBER}.${GITHUB_RUN_ATTEMPT}-${KSU_TYPE}"
  # KERNEL_MAKE_FLAGS is inherited from Resolve build profile via GITHUB_ENV.
  bash "${RKX_SOURCE}/scripts/build-custom-lkm.sh" \
    "$KERNEL_TREE" "$KERNEL_OUTPUT" "$CLANG_BIN" "$RKX_OUTPUT"

  {
    printf 'kernel_build_run=%s/%s/actions/runs/%s\n' \
      "${GITHUB_SERVER_URL:-https://github.com}" "${GITHUB_REPOSITORY:-local/OPSM8550-Kernel-Builder}" "${GITHUB_RUN_ID:-local}"
    printf 'kernel_release=%s\nroot_variant=%s\nclang=%s\n' "$EXPECTED_KERNEL_RELEASE" "$KSU_TYPE" "$CLANG_VERSION"
    printf 'kernel_base_commit=%s\n' "${KERNEL_COMMIT:-unknown}"
    printf 'rekernel_commit=%s\n' "$(git -C "$RKX_SOURCE" rev-parse HEAD)"
    printf 'kernel_image_sha256=%s\n' "$(sha256sum "${KERNEL_OUTPUT}/arch/arm64/boot/Image" | cut -d ' ' -f 1)"
  } > "${RKX_OUTPUT}/pairing-info.txt"
  (
    cd "$RKX_OUTPUT"
    sha256sum ./*.zip pairing-info.txt > SHA256SUMS
  )
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    {
      echo '### ReKernel-X companion module'
      echo "- Kernel: \`${EXPECTED_KERNEL_RELEASE}\`"
      echo "- Root variant: ${KSU_TYPE}"
      echo "- Source: \`$(git -C "$RKX_SOURCE" rev-parse HEAD)\`"
      echo '- Download the separate rekernel-x artifact from this run.'
      echo '- Use it with the kernel package from this same matrix job; device loading is not verified by CI.'
    } >> "$GITHUB_STEP_SUMMARY"
  fi
}

# Run in a subshell so set -e still stops on failures inside the function.
( build_module ) 2>&1 | tee "${RKX_OUTPUT}/build.log"
