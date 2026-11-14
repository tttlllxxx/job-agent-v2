import { spawn } from "node:child_process";
import { describe, it, expect } from "vitest";

function call(method: string) {
  return new Promise<Record<string, any>>((resolve, reject) => {
    const child = spawn(process.execPath, ["dist/index.js"], {
      stdio: ["pipe", "pipe", "pipe"],
    });
    let output = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("运行时协议超时"));
    }, 10000);
    child.stdout.on("data", (chunk) => {
      output += chunk.toString();
      if (output.includes("\n")) {
        clearTimeout(timer);
        child.kill();
        resolve(JSON.parse(output.split("\n")[0]));
      }
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.stdin.write(
      JSON.stringify({ jsonrpc: "2.0", id: 7, method, params: {} }) + "\n",
    );
  });
}
describe("受控运行时", () => {
  it("只公布求职业务工具", async () => {
    const result = await call("runtime.initialize");
    expect(result.id).toBe(7);
    expect(result.result.ready).toBe(true);
    expect(result.result.tools).toContain("update_context");
    expect(result.result.tools).toContain("manage_subscription");
    expect(result.result.tools).not.toContain("bash");
    expect(result.result.tools).not.toContain("submit_application");
  });
  it("未知方法返回结构化协议错误", async () => {
    const result = await call("unknown.method");
    expect(result.error.code).toBe(-32000);
  });
});
