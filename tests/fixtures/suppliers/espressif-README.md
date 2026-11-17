# Espressif source evidence

Reviewed on 2026-11-17. These small fixtures retain source links and verified
download hashes without embedding the full vendor sites or CAD payloads.

The official `espressif/kicad-libraries` tree at commit
`d5b68fd9269c639b3a60681e00b91df33b4db4a3` publishes STEP assemblies for
ESP32-WROOM-32E, ESP32-S3-WROOM-1, ESP32-C3-MINI-1, and ESP32-C6-WROOM-1.
Their downloaded payloads have `ISO-10303-21` headers. These are PCB-antenna
surface-mount modules, not complete development boards or external-antenna variants.

The root `LICENSE.md` covers the library under CC-BY-SA 4.0 with the published
KiCad exception for electronic designs and generated files. No nested license
files were found in the reviewed tree. The complete pinned notice is retained
in `espressif-KiCad-LICENSE.md` and is included as a downloadable document in
each module record. This grant is not inferred from an Espressif firmware license.

The official ESP32-DevKitC V4 and ESP32-S3-DevKitC-1 v1.1 guides link matching
DXF/PDF dimension drawings and board images. Their payloads were downloaded and
verified as DXF, PDF, and PNG respectively. The HTML fixtures retain those exact
mechanical links and image sources. No full-board STEP was found in the reviewed
official resources, so module geometry is not substituted for an assembled board.
These drawing and image assets keep unknown rights metadata.

`espressif-resources.json` records the URLs, byte sizes, and SHA-256 hashes of
the eleven distinct verified payloads. No current seller price, stock quantity,
or commercial SKU is asserted for these reference records.
