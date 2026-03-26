// @ts-nocheck
import { execFile } from "child_process";
import path from "path";

const SUBCOMMANDS = [
  "version",
  "init",
  "migrate",
  "validate",
  "graph",
  "run",
  "apply",
  "conformance",
  "handler",
  "legacy",
];

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      try { resolve(JSON.parse(Buffer.concat(chunks).toString())); }
      catch { resolve({}); }
    });
    req.on("error", reject);
  });
}

function runCli(pythonBin, repoRoot, pythonPath, args, timeoutMs) {
  return new Promise((resolve, reject) => {
    execFile(
      pythonBin,
      ["-m", "clawwrap.cli.main", ...args],
      {
        cwd: repoRoot,
        timeout: timeoutMs,
        env: {
          ...process.env,
          PYTHONPATH: pythonPath,
        },
      },
      (error, stdout, stderr) => {
        if (error) {
          resolve({
            success: false,
            error: error.message,
            stdout: stdout ?? "",
            stderr: stderr ?? "",
            exit_code: error.code ?? 1,
          });
          return;
        }

        resolve({
          success: true,
          stdout: stdout ?? "",
          stderr: stderr ?? "",
          exit_code: 0,
        });
      }
    );
  });
}

export function register(api) {
  const pluginConfig = api.config ?? {};

  const repoRoot =
    pluginConfig.repoRoot ??
    process.env.OPENCLAW_WORKSPACE ??
    process.cwd();

  const pythonBin =
    pluginConfig.pythonBin ??
    path.join(repoRoot, "clawpipe", ".venv", "bin", "python");

  const timeoutMs = pluginConfig.timeoutMs ?? 60000;

  const pythonPath = path.join(repoRoot, "clawwrap", "src");

  api.registerTool({
    name: "clawwrap",
    description:
      "Run ClawWrap outbound policy and conformance engine commands. Supports version, init, migrate, validate, graph, run, apply, conformance, handler, and legacy subcommands.",
    parameters: {
      type: "object",
      required: ["action"],
      additionalProperties: false,
      properties: {
        action: {
          type: "string",
          enum: SUBCOMMANDS,
          description:
            "The ClawWrap CLI subcommand to execute (version | init | migrate | validate | graph | run | apply | conformance | handler | legacy).",
        },
        config_path: {
          type: "string",
          description: "Optional path to a ClawWrap config file (--config).",
        },
        target: {
          type: "string",
          description:
            "Target identifier for validate/conformance subcommands.",
        },
        wrapper_id: {
          type: "string",
          description:
            "Wrapper identifier for run/apply/graph subcommands.",
        },
        subcommand: {
          type: "string",
          enum: ["list", "test", "bindings"],
          description:
            "Sub-action for the handler subcommand (list | test | bindings).",
        },
        verbose: {
          type: "boolean",
          description: "Enable verbose output (--verbose).",
        },
      },
    },
    handler: async (params) => {
      const { action, config_path, target, wrapper_id, subcommand, verbose } =
        params;

      const args = [action];

      if (config_path) {
        args.push("--config", config_path);
      }

      if (verbose) {
        args.push("--verbose");
      }

      if (target) {
        args.push(target);
      }

      if (wrapper_id) {
        args.push(wrapper_id);
      }

      if (subcommand) {
        args.push(subcommand);
      }

      return runCli(pythonBin, repoRoot, pythonPath, args, timeoutMs);
    },
  });

  // --- HTTP webhook routes ---

  api.registerHttpRoute({
    path: "/clawwrap/version",
    auth: "gateway",
    match: "exact",
    handler: async (req, res) => {
      try {
        const result = await runCli(pythonBin, repoRoot, pythonPath, ["version"], timeoutMs);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result));
      } catch (err) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ status: "error", error: err.message }));
      }
    },
  });

  api.registerHttpRoute({
    path: "/clawwrap/init",
    auth: "gateway",
    match: "exact",
    handler: async (req, res) => {
      const body = await readBody(req);
      const args = ["init"];
      if (body.config_path) args.push("--config", String(body.config_path));
      try {
        const result = await runCli(pythonBin, repoRoot, pythonPath, args, timeoutMs);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result));
      } catch (err) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ status: "error", error: err.message }));
      }
    },
  });

  api.registerHttpRoute({
    path: "/clawwrap/migrate",
    auth: "gateway",
    match: "exact",
    handler: async (req, res) => {
      const body = await readBody(req);
      const args = ["migrate"];
      if (body.config_path) args.push("--config", String(body.config_path));
      try {
        const result = await runCli(pythonBin, repoRoot, pythonPath, args, timeoutMs);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result));
      } catch (err) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ status: "error", error: err.message }));
      }
    },
  });

  api.registerHttpRoute({
    path: "/clawwrap/validate",
    auth: "gateway",
    match: "exact",
    handler: async (req, res) => {
      const body = await readBody(req);
      const args = ["validate"];
      if (body.config_path) args.push("--config", String(body.config_path));
      if (body.target) args.push(String(body.target));
      try {
        const result = await runCli(pythonBin, repoRoot, pythonPath, args, timeoutMs);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result));
      } catch (err) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ status: "error", error: err.message }));
      }
    },
  });

  api.registerHttpRoute({
    path: "/clawwrap/graph",
    auth: "gateway",
    match: "exact",
    handler: async (req, res) => {
      const body = await readBody(req);
      const args = ["graph"];
      if (body.config_path) args.push("--config", String(body.config_path));
      try {
        const result = await runCli(pythonBin, repoRoot, pythonPath, args, timeoutMs);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result));
      } catch (err) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ status: "error", error: err.message }));
      }
    },
  });

  api.registerHttpRoute({
    path: "/clawwrap/run",
    auth: "gateway",
    match: "exact",
    handler: async (req, res) => {
      const body = await readBody(req);
      const args = ["run"];
      if (body.config_path) args.push("--config", String(body.config_path));
      if (body.target) args.push(String(body.target));
      try {
        const result = await runCli(pythonBin, repoRoot, pythonPath, args, timeoutMs);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result));
      } catch (err) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ status: "error", error: err.message }));
      }
    },
  });

  api.registerHttpRoute({
    path: "/clawwrap/apply",
    auth: "gateway",
    match: "exact",
    handler: async (req, res) => {
      const body = await readBody(req);
      const args = ["apply"];
      if (body.config_path) args.push("--config", String(body.config_path));
      try {
        const result = await runCli(pythonBin, repoRoot, pythonPath, args, timeoutMs);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result));
      } catch (err) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ status: "error", error: err.message }));
      }
    },
  });

  api.registerHttpRoute({
    path: "/clawwrap/conformance",
    auth: "gateway",
    match: "exact",
    handler: async (req, res) => {
      const body = await readBody(req);
      const args = ["conformance"];
      if (body.config_path) args.push("--config", String(body.config_path));
      if (body.target) args.push(String(body.target));
      try {
        const result = await runCli(pythonBin, repoRoot, pythonPath, args, timeoutMs);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result));
      } catch (err) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ status: "error", error: err.message }));
      }
    },
  });

  api.registerHttpRoute({
    path: "/clawwrap/handler",
    auth: "gateway",
    match: "exact",
    handler: async (req, res) => {
      const body = await readBody(req);
      const args = ["handler"];
      if (body.subcommand) args.push(String(body.subcommand));
      try {
        const result = await runCli(pythonBin, repoRoot, pythonPath, args, timeoutMs);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result));
      } catch (err) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ status: "error", error: err.message }));
      }
    },
  });

  api.registerHttpRoute({
    path: "/clawwrap/legacy",
    auth: "gateway",
    match: "exact",
    handler: async (req, res) => {
      const body = await readBody(req);
      const args = ["legacy"];
      if (body.config_path) args.push("--config", String(body.config_path));
      try {
        const result = await runCli(pythonBin, repoRoot, pythonPath, args, timeoutMs);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result));
      } catch (err) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ status: "error", error: err.message }));
      }
    },
  });

  console.log("[clawwrap] tool + 10 HTTP routes registered");
}

export function activate(api) {
  register(api);
}

export default { register, activate };
