#!/usr/bin/env node

/**
 * VaultProxy Node.js CLI Wrapper
 * Allows running VaultProxy via `npx vaultproxy` or `npm install -g vaultproxy`.
 * Cross-platform: Linux, macOS, and Windows.
 */

const { spawnSync, spawn } = require("child_process");
const process = require("process");

const args = process.argv.slice(2);
const isWindows = process.platform === "win32";

function commandExists(cmd) {
  try {
    const testCmd = isWindows ? "where" : "which";
    const res = spawnSync(testCmd, [cmd], { stdio: "ignore" });
    return res.status === 0;
  } catch {
    return false;
  }
}

function runCommand(command, cmdArgs) {
  const child = spawn(command, cmdArgs, {
    stdio: "inherit",
    shell: isWindows,
  });

  child.on("close", (code) => {
    process.exit(code ?? 0);
  });

  child.on("error", (err) => {
    console.error(`[VaultProxy] Failed to execute ${command}:`, err.message);
    process.exit(1);
  });
}

function tryPythonModule(pyCmd) {
  try {
    const res = spawnSync(pyCmd, ["-c", "import vaultproxy"], {
      stdio: "ignore",
    });
    return res.status === 0;
  } catch {
    return false;
  }
}

function main() {
  // 1. Direct binary in PATH
  if (commandExists("vaultproxy")) {
    runCommand("vaultproxy", args);
    return;
  }

  // 2. Local Python environment with vaultproxy installed (fast & offline)
  const pyCandidates = isWindows
    ? ["python", "py", "python3"]
    : ["python3", "python"];

  for (const py of pyCandidates) {
    if (commandExists(py) && tryPythonModule(py)) {
      runCommand(py, ["-m", "vaultproxy", ...args]);
      return;
    }
  }

  // 3. uvx tool (downloads on-demand if online)
  if (commandExists("uvx")) {
    const res = spawnSync("uvx", ["vaultproxy", "--version"], { stdio: "ignore" });
    if (res.status === 0) {
      runCommand("uvx", ["vaultproxy", ...args]);
      return;
    }
  }

  // 4. pipx run (downloads on-demand if online)
  if (commandExists("pipx")) {
    const res = spawnSync("pipx", ["run", "vaultproxy", "version"], { stdio: "ignore" });
    if (res.status === 0) {
      runCommand("pipx", ["run", "vaultproxy", ...args]);
      return;
    }
  }

  // 5. Fallback guide if VaultProxy isn't installed in any detected python environment
  console.log("\n=== VaultProxy (OpenAI Privacy & Secret Leak Prevention Proxy) ===");
  console.log("\nVaultProxy requires the 'vaultproxy' package to be installed.");
  console.log("\nChoose one of the following quick installation methods:\n");
  console.log("  • Using uv (Fastest):");
  console.log("      uv tool install vaultproxy");
  console.log("\n  • Using pipx (Recommended for standalone CLI):");
  console.log("      pipx install vaultproxy");
  console.log("\n  • Using pip:");
  console.log("      pip install vaultproxy");
  console.log("\nOnce installed, you can run directly:\n");
  console.log("      vaultproxy run");
  console.log("      vaultproxy check --file .env\n");
  process.exit(1);
}

main();
