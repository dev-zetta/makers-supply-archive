# Raspberry Pi source review

Reviewed 2026-11-17. The JSON fixture records bounded downloads of official
Raspberry Pi resources; CAD binaries remain outside the test fixtures. Product
entries are mechanical or documentation references, with no inferred reseller
prices, stock, memory variants, or exact manufacturer SKU mappings.

| Product | Official resource | Verified content |
| --- | --- | --- |
| Raspberry Pi 5 | [Product portal](https://pip.raspberrypi.com/categories/892-raspberry-pi-5) | 13,270,704-byte ZIP; `rpi-5b_no_graphics.step`, 77,627,469 bytes; `LICENSE.txt` |
| Raspberry Pi 4 Model B | [Product portal](https://pip.raspberrypi.com/categories/545-raspberry-pi-4-model-b) | DXF mechanical drawing, 822,959 bytes; PDF mechanical drawing, 22,819 bytes |
| Raspberry Pi Pico | [Product portal](https://pip.raspberrypi.com/categories/610-raspberry-pi-pico) | 266,009-byte ZIP; `Pico-R3.step`, 1,721,174 bytes |
| Raspberry Pi Pico W | [Product portal](https://pip.raspberrypi.com/categories/686-raspberry-pi-pico-w) | 838,467-byte ZIP; `PicoW.stp`, 5,153,513 bytes |
| Raspberry Pi Pico 2 | [Product portal](https://pip.raspberrypi.com/categories/1005-raspberry-pi-pico-2) | 2,215,615-byte ZIP; `rpi_pico2.step`, 12,391,657 bytes; `LICENSE.txt` |
| Raspberry Pi Pico 2 W | [Product portal](https://pip.raspberrypi.com/categories/1088-raspberry-pi-pico-2-w) | Official datasheet PDF, 3,791,194 bytes; documentation-only entry |

The Pico R3 ZIP also contains the 731-byte AppleDouble resource-fork file
`__MACOSX/._Pico-R3.step`. It is metadata, not a second STEP model. The extractor
must ignore this member rather than reject the valid archive or expose it as CAD.

All four genuine STEP members begin with `ISO-10303-21`. The Pi 4 drawing uses an
ASCII DXF header; both reviewed PDF files begin with the PDF signature. Exact URLs,
sizes, SHA-256 values, and archive members are in `raspberry-pi-source-evidence.json`.

## License evidence

Pi 5 and Pico 2 ZIPs contain a model-specific disclaimer followed by an MIT license
with Raspberry Pi Ltd copyright notices. The exact included notices are preserved
in `raspberry-pi-5-MIT-LICENSE.txt` and `raspberry-pi-pico-2-MIT-LICENSE.txt`.
These apply to those particular 3D models, including incorporated third-party
models under the stated redistribution permission. Their disclaimer also says
the geometry is guidance, may differ from current products, and requires checking
against the physical hardware. The manifests link the original ZIP as the license
source so its notice remains associated with the extracted geometry.

The current official [Pico-series hardware documentation](https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html)
lists the Pico and Pico W STEP resources and expressly permits using, copying,
modifying, and distributing their design files. Those two assets are marked
permissive with that documentation as the license source. This is a hardware
design-file grant, not an inference from firmware or repository licensing.
Pi 4 drawing and Pico 2 W document rights remain unknown in this review.

## Compatibility boundaries

The Pi 4 resources are two-dimensional drawings. They are not represented as a
three-dimensional board model. A dated model file or document version does not
identify the user's physical board revision. Pico R3 is the only entry given a
hardware revision directly evidenced by its source model name.

The current Pico 2 W portal and its section in the Pico-series documentation list
documentation and schematics without a distinct STEP download. Its datasheet
mentions a Pico 2 STEP resource, which resolves to the non-wireless Pico 2 archive.
That model is deliberately not attached to Pico 2 W. Likewise, Pico/Pico W models
are not silently reused for second-generation or presoldered-header variants.

The product descriptions and specifications are short factual paraphrases of
the official [Pi 5 product page](https://www.raspberrypi.com/products/raspberry-pi-5/),
[Pi 4 product page](https://www.raspberrypi.com/products/raspberry-pi-4-model-b/),
and Pico-series documentation. Source-page access returned HTTP 403 for the
direct Pico-series documentation request, while the browsing source exposed its
current contents; the portal pages and all declared asset downloads returned 200.
No access restriction was bypassed.
