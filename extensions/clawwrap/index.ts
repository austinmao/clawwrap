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

      const args = ["-m", "clawwrap.cli.main", action];

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

      return new Promise((resolve, reject) => {
        execFile(
          pythonBin,
          args,
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
    },
  });

  console.log("[clawwrap] tool registered");
}

export function activate(api) {
  register(api);
}

export default { register, activate };
