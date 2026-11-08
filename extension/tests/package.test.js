import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync,existsSync} from "node:fs";
import vm from "node:vm";
import "../booking-rules.js";
const read=path=>readFileSync(new URL("../"+path,import.meta.url),"utf8");
test("Manifest 仅声明已批准的学校权限，所有入口存在",()=>{
  const m=JSON.parse(read("manifest.json"));assert.equal(m.manifest_version,3);
  assert.deepEqual(m.host_permissions,["https://sports.sjtu.edu.cn/*"]);
  assert.deepEqual([...m.permissions].sort(),["storage","alarms","sidePanel","notifications","offscreen"].sort());
  for(const file of [m.background.service_worker,m.side_panel.default_path,...m.content_scripts.flatMap(s=>s.js),...Object.values(m.icons)]) assert.ok(existsSync(new URL("../"+file,import.meta.url)),file);
  assert.equal(m.content_scripts[0].all_frames,false);
});
test("插件的规则文件与 Python 读取的源文件一致",()=>{
  const source=readFileSync(new URL("../../sjtu_tennis_toolkit/booking_rules.json",import.meta.url),"utf8");
  assert.deepEqual(globalThis.SJTU_BOOKING_RULES,JSON.parse(source));
  const manifest=JSON.parse(read("manifest.json"));
  assert.deepEqual(manifest.host_permissions,[globalThis.SJTU_BOOKING_RULES.schoolOrigin+"/*"]);
});
test("页面探针是静态可执行函数，无 eval 或远程加载",()=>{
  const sandbox={};
  vm.runInNewContext(read("booking-rules.js"),sandbox);
  vm.runInNewContext(read("probes.js"),sandbox);
  for(const name of ["cell","scan","dates","grid","notice","scroll"]) assert.equal(typeof sandbox.SJTU_PROBES[name],"function");
  assert.equal(sandbox.SJTU_PROBES.geometry.courtCount,globalThis.SJTU_BOOKING_RULES.courtCount);
  for(const file of ["content.js","probes.js","background.js","controller.js","sidepanel.js"]) assert.doesNotMatch(read(file),/\beval\s*\(|new\s+Function\s*\(/);
});
