# Waveshare expansion fixtures

Reviewed on 2026-11-17. The two HTML fixtures are minimal reductions of actual
official storefront responses. They retain all published SKU options for exclusion
tests, a small gallery thumbnail before the main 560px image, and no inferred
per-SKU prices or stock quantities.

- `waveshare-expansion-25081.html`: https://www.waveshare.com/esp32-s3-zero.htm
  and https://docs.waveshare.com/ESP32-S3-Zero. SKU 25081 is the 4MB Flash /
  2MB PSRAM option without headers. The 25517, 33879, and 33549 options are
  intentionally retained in the fixture to test exclusion.
- `waveshare-expansion-25948.html`:
  https://www.waveshare.com/esp32-s3-touch-lcd-4.3.htm and
  https://docs.waveshare.com/ESP32-S3-Touch-LCD-4.3. SKU 25948 has touch
  function; 30493 does not. Both remain in the fixture.

The resource pages directly publish these CAD links:

- https://docs.waveshare.com/ESP32-S3-Zero/Resources-And-Documents links the
  `ESP32-S3-Zero_v2-138eb3753cf14afa3252058c380ca416.stp` file. Its payload
  starts with `ISO-10303-21`. The filename includes `v2`, but this does not
  establish the physical board revision sold under SKU 25081.
- https://docs.waveshare.com/ESP32-S3-Touch-LCD-4.3/Resources-And-Documents
  links `ESP32-S3-Touch-LCD-4in3_3D_Drawing.zip`, containing
  `esp32-s3-touch-lcd-4_3.stp`.

The official legacy wiki pages at
https://www.waveshare.com/wiki/RP2040-Zero and
https://www.waveshare.com/wiki/RP2350-Zero were indexed with their STEP resources
but returned HTTP 502 to the research client. The exact links were recovered from
published printed copies of those wiki pages, then the payloads were verified
directly on the official `files.waveshare.com` host:

- https://ja-bots.com/wp-content/uploads/2026/02/B1lpcxQMsVL.pdf lists
  https://files.waveshare.com/upload/f/f7/RP2040_Zero_stp.zip. The official ZIP
  contains `RP2040_Zero.stp`, with a STEP header and RP2040 Zero assembly name.
- https://manuals.plus/m/587ed206eb5a7f8bd470d86fd6be23ad4b27be12e97c3ee808d3c1b1ca617948
  lists https://files.waveshare.com/wiki/RP2350-Zero/RP2350_Zero_step.zip.
  The official ZIP contains `RP2350-Zero.step` with a STEP header.

The RP2040/RP2350 entries are mechanical references with no inferred current
storefront SKU, price, stock, or pre-soldered-header compatibility. The manifest
keeps Waveshare as board manufacturer and Raspberry Pi as the MCU designer.

Original content remains the property of its rights holders. Public downloads do
not establish a CAD redistribution license; these assets retain unknown rights.
