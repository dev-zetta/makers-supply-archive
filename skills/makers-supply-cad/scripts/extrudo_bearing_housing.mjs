#!/usr/bin/env node
// Executable EA028 integration example. Extrudo remains an external dependency.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, lstatSync, mkdtempSync, readFileSync, realpathSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';

const HELP = `EA028 bearing housing with Extrudo's actual headless kernel (Node 24+).
Usage: node extrudo_bearing_housing.mjs --extrudo SOURCE_CHECKOUT
       --reference VERIFIED_CATALOG_EXPORT --output NEW_DIRECTORY
The output parent must exist. Run pnpm install and pnpm wasm in Extrudo first.
This example checks the catalog's EA028 source table and EU 2PCS variant.
All housing dimensions and clearances are prototype design choices.`;

const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
function pathExists(path) {
  try { lstatSync(path); return true; }
  catch (error) { if (error.code === 'ENOENT') return false; throw error; }
}
const json = (file) => JSON.parse(readFileSync(file, 'utf8'));
function sourceRevision(runtime) {
  // A source tarball is usable too; Git is not a CAD runtime dependency.
  const headPath = join(runtime, '.git/HEAD');
  if (!existsSync(headPath)) return null;
  const head = readFileSync(headPath, 'utf8').trim();
  if (!head.startsWith('ref: ')) return head;
  const refPath = join(runtime, '.git', head.slice(5));
  return existsSync(refPath) ? readFileSync(refPath, 'utf8').trim() : null;
}
const writeJson = (file, value) => writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`);
const near = (actual, expected, tolerance = 1e-5) => {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} differs from ${expected}`);
};
const clean = (result) => {
  assert.equal(result.errors, 0, JSON.stringify(result.features));
  assert.equal(result.warnings, 0, JSON.stringify(result.features));
};

async function main() {
  const { values } = parseArgs({ options: {
    extrudo: { type: 'string' }, reference: { type: 'string' },
    output: { type: 'string' }, help: { type: 'boolean' },
  } });
  if (values.help) { console.log(HELP); return; }
  assert.ok(Number(process.versions.node.split('.')[0]) >= 24, 'Node 24+ is required');
  assert.ok(values.extrudo && values.reference && values.output, HELP);
  const runtime = resolve(values.extrudo);
  const reference = realpathSync(resolve(values.reference));
  const output = resolve(values.output);
  assert.ok(!pathExists(output), 'Output must be a new directory');
  const product = json(join(reference, 'product.json'));
  const manifest = json(join(reference, 'manifest.json'));
  assert.equal(manifest.format, 'makers-supply-cad');
  assert.equal(product.id, 'ea028-high-performance-bearings');
  assert.equal(manifest.product_id, product.id);
  const variant = product.variants.find((v) => v.region === 'eu' && v.part_number === 'EA028');
  assert.ok(variant && /2PCS/i.test(variant.title), 'Expected the verified EU EA028 two-piece pack');
  const table = product.source_tables.find((t) => t.rows.some((r) => r[0] === 'EA028'));
  assert.ok(table, 'EA028 source table is required');
  const row = table.rows.find((r) => r[0] === 'EA028');
  assert.match(table.headers[2], /Inside Diameter/);
  assert.match(table.headers[3], /Outer Diameter/);
  assert.match(table.headers[4], /Width/);
  const [bore, od, width] = row.slice(2, 5).map(Number);
  assert.deepEqual([bore, od, width], [8, 22, 7], 'This example is specifically for EA028');
  const asset = manifest.assets.find((a) => a.id === 'model-3f4ff15eee8cf265bc90');
  assert.ok(asset?.verified && /\.stp$/i.test(asset.original_filename));
  const assetPath = realpathSync(resolve(reference, asset.package_path));
  const local = relative(reference, assetPath);
  assert.ok(local && !isAbsolute(local) && !local.startsWith(`..${sep}`) && local !== '..',
    'Unsafe reference path');
  const step = new Uint8Array(readFileSync(assetPath));
  assert.equal(step.byteLength, asset.size);
  assert.equal(hash(step), asset.sha256, 'Reference bytes have changed since catalog export');

  // Absolute entrypoints work from an installed skill outside pnpm's workspace.
  await import(pathToFileURL(join(runtime, 'scripts/ts-import.mjs')).href);
  const load = (path) => import(pathToFileURL(join(runtime, path)).href);
  const [{ Design }, { addAttachment }, { writeArchive }, { openDesign }, kernel] = await Promise.all([
    load('packages/api/src/index.ts'), load('packages/core/src/index.ts'),
    load('packages/storage/src/index.ts'), load('packages/cli/src/headless.ts'),
    load('packages/kernel/src/node.ts'),
  ]);
  const attachmentId = 'catalog-ea028-step';
  function attach(design, id, name, bytes) {
    const sha256 = hash(bytes);
    design.state.dispatch(addAttachment({ id, attachment: {
      name, fileName: name, mediaType: 'model/step', sha256, size: bytes.byteLength,
    } }));
    return new Map([[sha256, bytes]]);
  }
  const encode = (design, attachments) => writeArchive(design.toJSON(), undefined, [], attachments);
  async function compute(bytes) {
    const { job, notices } = await openDesign(bytes);
    try {
      assert.deepEqual(notices, [], 'Native archive has missing or invalid attachments');
      const report = await job.compute();
      clean(report);
      return report;
    } finally { await job.dispose(); }
  }
  async function inspect(doc) {
    const service = new kernel.KernelService(() => kernel.loadOcct());
    try {
      await service.init();
      await service.addFile(attachmentId, step.slice().buffer, 'model/step', asset.original_filename);
      const result = await service.recompute({ doc });
      assert.equal(result.status, 'done');
      const ids = result.bodies.map((b) => b.id);
      return {
        measures: await service.measureBodies(ids),
        interference: await service.interference(ids),
        meshes: result.bodies.map((b) => ({ id: b.id, positions: [...b.mesh.positions],
          normals: [...b.mesh.normals], indices: [...b.mesh.indices] })),
      };
    } finally { service.dispose(); }
  }
  const d = Design.create({ name: 'EA028 bearing flange housing', units: 'mm' });
  const parameters = {
    bearing_bore: `${bore} mm`, bearing_od: `${od} mm`, bearing_width: `${width} mm`,
    diametral_clearance: '0.2 mm', axial_recess: '0.2 mm',
    plate_length: '44 mm', plate_width: '32 mm', plate_thickness: '4 mm',
    boss_diameter: '30 mm', boss_height: '8 mm', shaft_relief: '18 mm',
    mount_diameter: '3.4 mm', mount_x: '17 mm', mount_y: '10 mm',
    seat_diameter: 'bearing_od + diametral_clearance',
    seat_depth: 'bearing_width + axial_recess',
    seat_floor: 'plate_thickness + boss_height - seat_depth',
  };
  for (const [name, expression] of Object.entries(parameters)) d.parameter(name, expression);
  const plate = d.box({ length: 'plate_length', width: 'plate_width', height: 'plate_thickness' },
    { name: 'Mounting flange' });
  d.cylinder({ diameter: 'boss_diameter', height: 'boss_height', offset: 'plate_thickness',
    operation: 'join', bodies: plate.body() }, { name: 'Bearing boss' });
  d.cylinder({ diameter: 'seat_diameter', height: 'seat_depth', offset: 'seat_floor',
    operation: 'cut', bodies: plate.body() }, { name: 'EA028 clearance seat' });
  d.cylinder({ diameter: 'shaft_relief', height: 'plate_thickness + boss_height',
    operation: 'cut', bodies: plate.body() }, { name: 'Shaft and inner race relief' });
  for (const sx of [-1, 1]) for (const sy of [-1, 1]) {
    d.cylinder({ diameter: 'mount_diameter', height: 'plate_thickness',
      x: `${sx} * mount_x`, y: `${sy} * mount_y`, operation: 'cut', bodies: plate.body() },
    { name: `Mount hole ${sx},${sy}` });
  }
  d.setBody(plate.body(), { name: 'Housing', color: '#247cad' });
  const attachments = attach(d, attachmentId, asset.original_filename, step);
  const imported = d.import({ file: attachmentId, position: 'file', units: 'auto' },
    { name: 'Catalog EA028 reference' });
  const initial = await compute(encode(d, attachments));
  const references = initial.bodies.filter((b) => b.id.startsWith(`${imported.id}:`));
  assert.equal(references.length, 2, 'EA028 STEP must import both solid bodies');
  for (const body of references) assert.equal(body.mesh, false);
  // This source STEP is X-axis oriented. Centering does not rotate it.
  const mins = [0, 1, 2].map((i) => Math.min(...references.map((b) => b.min[i])));
  const sizes = [0, 1, 2].map((i) => Math.max(...references.map((b) => b.min[i] + b.size[i])) - mins[i]);
  sizes.forEach((v, i) => near(v, [width, od, od][i], 0.03));
  d.moveBodies({ bodies: references.map((b) => d.ref('body', b.id)), ry: '-90 deg',
    dz: 'seat_floor + bearing_width / 2' }, { name: 'Seat both EA028 reference solids' });
  references.forEach((b, i) => d.setBody(d.ref('body', b.id), {
    name: `EA028 reference solid ${i + 1}`, color: '#b5bbc4',
  }));
  assert.deepEqual(d.validate(), []);
  const bytes = encode(d, attachments);
  const report = await compute(bytes);
  assert.equal(report.bodies.length, 3);
  const housing = report.bodies.find((b) => b.name === 'Housing');
  assert.ok(housing && !housing.mesh);
  housing.size.forEach((v, i) => near(v, [44, 32, 12][i], 0.001));
  const volume = (clearance) => 44 * 32 * 4 + Math.PI * 15 ** 2 * 8
    - Math.PI * 9 ** 2 * 4.8 - Math.PI * ((22 + clearance) / 2) ** 2 * 7.2
    - 4 * Math.PI * 1.7 ** 2 * 4;
  near(housing.volume, volume(0.2));
  const exact = await inspect(d.toJSON());
  assert.equal(exact.measures[housing.id].solids, 1);
  assert.deepEqual(exact.interference, [], 'Bearing intersects the housing');
  const temporary = mkdtempSync(join(dirname(output), '.extrudo-housing-'));
  let job;
  try {
    writeFileSync(join(temporary, 'bearing-housing.extrudo'), bytes);
    ({ job } = await openDesign(bytes));
    const exports = [];
    let housingStep;
    for (const format of ['step', 'stl', '3mf']) {
      const [file] = await job.export({ format, bodies: ['Housing'], resolution: 'fine' });
      assert.ok(file.bytes.length > 0);
      assert.equal(file.closed, true, `Exported ${format} is not closed`);
      const name = `housing.${format}`;
      writeFileSync(join(temporary, name), file.bytes);
      exports.push({ name, sha256: hash(file.bytes), bytes: file.bytes.length,
        bodies: file.bodies, triangles: file.triangles, closed: file.closed });
      if (format === 'step') housingStep = file.bytes;
    }
    const back = Design.create({ name: 'Housing STEP round trip', units: 'mm' });
    const backFiles = attach(back, 'housing-step', 'housing.step', housingStep);
    back.import({ file: 'housing-step', position: 'file' });
    const reimport = await compute(encode(back, backFiles));
    assert.equal(reimport.bodies.length, 1);
    near(reimport.bodies[0].volume, housing.volume, 1e-4);
    reimport.bodies[0].size.forEach((v, i) => near(v, housing.size[i], 0.001));
    await job.setParameters({ diametral_clearance: '0.4 mm' });
    const changed = await job.compute(); clean(changed);
    near(changed.bodies.find((b) => b.name === 'Housing').volume, volume(0.4));
    await job.save(join(temporary, 'clearance-0.4.extrudo'));
    await job.setParameters({ diametral_clearance: '-0.2 mm' });
    const negative = await job.compute(); clean(negative);
    const interference = (await inspect(job.doc)).interference;
    assert.ok(interference.some((p) => p.a === housing.id || p.b === housing.id),
      'Negative control failed to detect an undersized seat');
    const bom = { items: [{ product_id: product.id, region: variant.region,
      variant_id: variant.variant_id, part_number: variant.part_number,
      quantity: 1, quantity_unit: 'pack', pack_size: 2, physical_part_quantity: 1,
      spare_part_quantity: 1, reference_manifest: relative(output, join(reference, 'manifest.json')),
      source_asset: { id: asset.id, sha256: asset.sha256, rights_status: asset.rights_status,
        source_url: asset.source_url, parent_asset_id: asset.parent_asset_id,
        archive_member_path: asset.archive_member_path },
      dimensions: { bore_mm: bore, od_mm: od, width_mm: width, provenance: table.provenance },
    }] };
    writeJson(join(temporary, 'hardware-bom.json'), bom);
    writeJson(join(temporary, 'preview-meshes.json'), exact.meshes);
    const evidence = { extrudo_version: json(join(runtime, 'package.json')).version,
      extrudo_revision: sourceRevision(runtime),
      mode: 'headless OCCT, no desktop MCP session', parameters,
      import: { source_sizes_mm: sizes, bodies: references.length, rotation_y_degrees: -90 },
      model: report, exact_measures: exact.measures, interference: exact.interference,
      expected_housing_volume_mm3: volume(0.2), exports, step_reimport: reimport,
      parameter_change: { diametral_clearance_mm: 0.4, model: changed },
      negative_control: { diametral_clearance_mm: -0.2, detected_interference: interference },
      limitations: ['Prototype slip-fit allowance; physical fit has not been tested.',
        'Open-top housing has no axial retainer; manufacturing and retention require review.'] };
    writeJson(join(temporary, 'validation.json'), evidence);
    assert.ok(!pathExists(output), 'Output appeared during execution');
    renameSync(temporary, output);
    console.log(JSON.stringify({ output, housing_volume_mm3: housing.volume,
      bodies: report.bodies.length, exports, passed: true }, null, 2));
  } finally {
    if (job) await job.dispose();
    if (existsSync(temporary)) rmSync(temporary, { recursive: true });
  }
}

main().catch((error) => { console.error(`extrudo housing: ${error.message}`); process.exitCode = 1; });
