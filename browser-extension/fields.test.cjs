const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync(__dirname + "/sidepanel.js", "utf8");
const fieldsCode = source.slice(
  source.indexOf("function scanPage()"),
  source.indexOf("function renderPreview()"),
);
function control(overrides = {}) {
  return {
    id: "email",
    name: "email",
    type: "text",
    value: "",
    checked: false,
    labels: [{ innerText: "邮箱" }],
    getAttribute: () => null,
    getClientRects: () => [{}],
    dispatchEvent: () => {},
    ...overrides,
  };
}
function page(controls) {
  const location = { href: "https://example.test/apply" };
  const tools = vm.runInNewContext(fieldsCode + ";({scanPage,fillPage})", {
    location,
    document: {
      querySelectorAll: () => controls,
      querySelector: () => null,
      body: { innerText: "申请表" },
    },
    getComputedStyle: () => ({ visibility: "visible" }),
    Event: class Event {},
  });
  return { ...tools, location };
}
function grant(snapshot, action, overwrite = []) {
  return {
    url: snapshot.url,
    fields: snapshot.fields,
    actions: [action],
    overwrite,
  };
}
test("重名字段独立标识，未勾选控件不算已有值", () => {
  const p = page([
    control({ name: "shared", id: "", type: "checkbox", value: "on" }),
    control({ name: "shared", id: "" }),
  ]);
  const snapshot = p.scanPage();
  assert.notEqual(snapshot.fields[0].key, snapshot.fields[1].key);
  assert.equal(snapshot.fields[0].has_value, false);
  assert.equal(snapshot.fields[0].value, false);
});
test("授权取消勾选后按实际勾选状态回读验证", () => {
  const checkbox = control({ type: "checkbox", checked: true });
  const p = page([checkbox]);
  const snapshot = p.scanPage();
  const result = p.fillPage(
    grant(snapshot, { key: snapshot.fields[0].key, index: 0, value: false }, [
      snapshot.fields[0].key,
    ]),
  );
  assert.equal(checkbox.checked, false);
  assert.equal(result[0].verified, true);
});
test("用户在预览后修改原值，未经覆盖授权时停止", () => {
  const input = control({ value: "before" });
  const p = page([input]);
  const snapshot = p.scanPage();
  input.value = "user correction";
  assert.throws(
    () =>
      p.fillPage(
        grant(snapshot, {
          key: snapshot.fields[0].key,
          index: 0,
          value: "new",
        }),
      ),
    /已有值变化/,
  );
  assert.equal(input.value, "user correction");
});
test("授权不能跨页面执行", () => {
  const p = page([control()]);
  const snapshot = p.scanPage();
  p.location.href = "https://example.test/other";
  assert.throws(
    () =>
      p.fillPage(
        grant(snapshot, {
          key: snapshot.fields[0].key,
          index: 0,
          value: "new",
        }),
      ),
    /页面已变化/,
  );
});
