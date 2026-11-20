# ONNX Runtime ARM64 source archive

This package includes the original `onnxruntime-linux-aarch64-1.22.0.tgz`
release archive used by the firmware. Its SHA-256 matches the existing pinned
hash in `onnxruntime-aarch64.hash`:

`bb76395092d150b52c7092dc6b8f2fe4d80f0f3bf0416d2f269193e347e24702`

Original source:
https://github.com/microsoft/onnxruntime/releases/download/v1.22.0/onnxruntime-linux-aarch64-1.22.0.tgz

The upstream URL returned HTTP 404 during the 0.2.26 and 0.2.27 release builds.
The archive was recovered from a previously downloaded local Buildroot cache;
its bytes match the hash committed before those builds. Buildroot copies this
archive locally and still verifies its hash before extraction. The runtime
version and installed libraries have not changed.

The archive contains the MIT `LICENSE` and `ThirdPartyNotices.txt` used by the
package's existing license declaration.
