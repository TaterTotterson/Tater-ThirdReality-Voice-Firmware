# Security model

This fork does not ship the vendor image's remote administration defaults.

- The root password is locked.
- Dropbear/SSH is absent from the production defconfig.
- `adbd` is absent. Its retained init script is also opt-in and has TCP
  disabled, which makes accidental reintroduction fail closed.
- The Tater peripheral WebSocket listens only on `127.0.0.1`.
- Satellite authentication is outbound to Tater; the paired token is stored
  mode 0600 under `/data/conf`.
- The upstream SWUpdate private key and matching public key were removed.
  Every build derives its embedded public key from externally supplied signing
  material, and the private key is removed from OTA staging after signing.

The serial header still opens a local root recovery shell. Treat physical access
to the debug header as administrative access. This is intentional for the
development-edition hardware and is the current Tater provisioning path.

This work rekeys the SWUpdate path only. It does not claim ownership of the
Amlogic secure-boot root. The vendor U-Boot tree includes development key
material for other Amlogic reference boards; the selected
`axg_s420_v1_trspk` target has no `aml-key` directory, but its proprietary
boot-FIP chain still needs hardware verification and a vendor-supported rekeying
process before this can be called a production-owned secure-boot chain.

## OTA signing

Production CI must define the masked repository secret
`TATER_SWUPDATE_PRIVATE_KEY_PEM`. Generate and escrow that key outside the
repository.

For disposable development images only:

```sh
./script/generate_development_ota_key.sh
TATER_SWUPDATE_PRIVATE_KEY_FILE=.secrets/swupdate-development-private.pem \
  ./go --docker trspk
```

Do not deploy development-key images as a maintained fleet: devices trust the
public key embedded in the image, so future OTA files must use the same private
key.
