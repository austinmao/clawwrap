"""OpenClaw handler binding: outbound.submit.

Universal outbound message gate entry point. Every agent-initiated send
passes through this handler. Orchestrates: resolve -> verify -> dispatch -> audit.

The gate validates the TARGET, not the PERMISSION to send. Human approval
(Constitution Principle I) remains the calling skill's responsibility.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from clawwrap.engine.gate import (
    GateVerdict,
    OutboundRequest,
    ResolvedContext,
    make_request_id,
    now_iso,
)
from clawwrap.gate.audit import log_verdict
from clawwrap.gate.dispatch import dispatch_to_channel
from clawwrap.gate.resolve import load_targets, resolve_direct, resolve_shared
from clawwrap.gate.verify import evaluate_checks, load_gateway_config, load_policy
from clawwrap.handlers.registry import handler

# Default paths — overridable via inputs for testing.
_DEFAULT_CONFIG_DIR: Path = Path(__file__).resolve().parents[5] / "config"
_DEFAULT_GATEWAY_PATH: Path = Path.home() / ".openclaw" / "openclaw.json"
_DEFAULT_LOG_DIR: Path = Path("memory") / "logs" / "outbound"


@handler("outbound.submit", adapter_name="openclaw")
def submit(inputs: dict[str, Any]) -> dict[str, Any]:
    """Universal outbound gate entry point.

    Contract inputs:
        route_mode (str): "shared" or "direct".
        context_key (str, optional): For shared routes.
        audience (str, optional): For shared routes.
        recipient_ref (str, optional): For direct routes.
        channel (str): Target channel.
        message (str): Message body.
        requested_by (str): Skill name.
        dry_run (bool, optional): Resolve + verify only.
        config_dir (str, optional): Override config directory path.
        gateway_path (str, optional): Override gateway config path.
        log_dir (str, optional): Override audit log directory.

    Contract outputs:
        Full GateVerdict dict (see engine/gate.py).
    """
    request_id = make_request_id()
    timestamp = now_iso()
    adapter = _build_adapter()

    # Parse config overrides
    config_dir = Path(inputs["config_dir"]) if inputs.get("config_dir") else _DEFAULT_CONFIG_DIR
    gateway_path = Path(inputs["gateway_path"]) if inputs.get("gateway_path") else _DEFAULT_GATEWAY_PATH
    audit_log_dir = Path(inputs["log_dir"]) if inputs.get("log_dir") else _DEFAULT_LOG_DIR
    resolver_registry = _build_resolver_registry()

    # Build and validate request
    req = OutboundRequest(
        route_mode=str(inputs.get("route_mode", "")),
        channel=str(inputs.get("channel", "")),
        message=str(inputs.get("message", "")),
        requested_by=str(inputs.get("requested_by", "")),
        context_key=inputs.get("context_key"),
        audience=inputs.get("audience"),
        recipient_ref=inputs.get("recipient_ref"),
        dry_run=bool(inputs.get("dry_run", False)),
        payload=inputs.get("payload"),
    )

    validation_error = req.validate()
    if validation_error:
        verdict = _deny_verdict(request_id, timestamp, req, validation_error)
        _audit(verdict, audit_log_dir)
        return verdict.to_dict()

    # --- RESOLVE ---
    resolved: ResolvedContext
    try:
        if req.route_mode == "shared":
            targets_data = load_targets(config_dir)
            resolved = resolve_shared(req.context_key or "", req.audience or "", req.channel, targets_data)
        else:
            resolved = resolve_direct(req.recipient_ref or "", req.channel, resolver_registry)
    except FileNotFoundError as exc:
        verdict = _deny_verdict(request_id, timestamp, req, f"targets directory unreadable: {exc}")
        _audit(verdict, audit_log_dir)
        return verdict.to_dict()
    except ValueError as exc:
        verdict = _deny_verdict(request_id, timestamp, req, f"resolution failed: {exc}")
        _audit(verdict, audit_log_dir)
        return verdict.to_dict()
    except Exception as exc:
        verdict = _deny_verdict(request_id, timestamp, req, f"resolve error: {exc}")
        _audit(verdict, audit_log_dir)
        return verdict.to_dict()

    # --- VERIFY ---
    try:
        policy = load_policy(config_dir)
    except Exception as exc:
        verdict = _deny_verdict(
            request_id, timestamp, req,
            f"outbound policy unreadable: {exc}",
            resolved=resolved,
        )
        _audit(verdict, audit_log_dir)
        return verdict.to_dict()

    try:
        resolved = _apply_live_identity_verification(resolved, req.channel, adapter.bind_handler)
    except Exception as exc:
        verdict = _deny_verdict(
            request_id,
            timestamp,
            req,
            f"live identity verification unavailable: {exc}",
            resolved=resolved,
        )
        _audit(verdict, audit_log_dir)
        return verdict.to_dict()

    gateway_config = load_gateway_config(gateway_path)

    checks = evaluate_checks(resolved, req.route_mode, req.channel, policy, gateway_config)
    failed = [c for c in checks if not c.passed]

    if failed:
        denied_by = failed[0].name
        reason = f"denied by {denied_by}: {failed[0].detail}"
        verdict = GateVerdict(
            allowed=False,
            request_id=request_id,
            target=resolved.target,
            audience_label=resolved.audience_label,
            channel=req.channel,
            requested_by=req.requested_by,
            verification_supported=resolved.verification_supported,
            live_identity=resolved.live_identity,
            checks=checks,
            denied_by=denied_by,
            reason=reason,
            timestamp=timestamp,
        )
        _audit(verdict, audit_log_dir)
        return verdict.to_dict()

    # --- DISPATCH (skip on dry_run) ---
    send_result: dict[str, Any] | list[dict[str, Any]] | None = None
    if not req.dry_run and resolved.target:
        try:
            if isinstance(resolved.target, list):
                # Email list fan-out: dispatch to each address individually.
                results: list[dict[str, Any]] = []
                for addr in resolved.target:
                    r = dispatch_to_channel(
                        target=addr,
                        channel=req.channel,
                        message=req.message,
                        dry_run=req.dry_run,
                        bind_handler=adapter.bind_handler,
                        payload=req.payload,
                    )
                    results.append(r)
                send_result = results
            else:
                send_result = dispatch_to_channel(
                    target=resolved.target,
                    channel=req.channel,
                    message=req.message,
                    dry_run=req.dry_run,
                    bind_handler=adapter.bind_handler,
                    payload=req.payload,
                )
        except Exception as exc:
            send_result = {"message_id": "", "sent_at": "", "detail": f"dispatch error: {exc}"}

    # --- BUILD VERDICT ---
    verdict = GateVerdict(
        allowed=True,
        request_id=request_id,
        target=resolved.target,
        audience_label=resolved.audience_label,
        channel=req.channel,
        requested_by=req.requested_by,
        verification_supported=resolved.verification_supported,
        live_identity=resolved.live_identity,
        checks=checks,
        denied_by=None,
        reason=f"{'dry_run: ' if req.dry_run else ''}sent to {resolved.audience_label} via {req.channel}",
        timestamp=timestamp,
        send_result=send_result,
    )

    # --- AUDIT ---
    _audit(verdict, audit_log_dir)

    return verdict.to_dict()


def _deny_verdict(
    request_id: str,
    timestamp: str,
    req: OutboundRequest,
    reason: str,
    resolved: ResolvedContext | None = None,
) -> GateVerdict:
    """Build a deny verdict for early-exit error paths."""
    return GateVerdict(
        allowed=False,
        request_id=request_id,
        target=resolved.target if resolved else None,
        audience_label=resolved.audience_label if resolved else "",
        channel=req.channel,
        requested_by=req.requested_by,
        verification_supported=resolved.verification_supported if resolved else False,
        live_identity=None,
        checks=[],
        denied_by="infrastructure",
        reason=reason,
        timestamp=timestamp,
    )


def _audit(verdict: GateVerdict, log_dir: Path) -> None:
    """Best-effort audit logging."""
    try:
        log_verdict(verdict.to_dict(), log_dir)
    except Exception:
        pass  # audit is best-effort


def _build_adapter() -> Any:
    from clawwrap.adapters.openclaw.adapter import OpenClawAdapter

    return OpenClawAdapter()


def _build_resolver_registry() -> dict[str, Any]:
    from clawwrap.adapters.openclaw.resolvers import build_resolver_registry

    return build_resolver_registry()


def _apply_live_identity_verification(
    resolved: ResolvedContext,
    channel: str,
    bind_handler: Any,
) -> ResolvedContext:
    if channel == "whatsapp":
        return _verify_whatsapp_identity(resolved, bind_handler)
    if channel == "slack":
        return _verify_slack_identity(resolved, bind_handler)
    if channel == "mailchimp":
        return _verify_mailchimp_identity(resolved, bind_handler)
    return resolved


def _verify_whatsapp_identity(
    resolved: ResolvedContext,
    bind_handler: Any,
) -> ResolvedContext:
    if not resolved.target or not isinstance(resolved.target, str) or not resolved.target.endswith("@g.us"):
        return resolved
    if not isinstance(resolved.expected_identity, dict):
        return resolved

    expected_title = str(resolved.expected_identity.get("title", "")).strip()
    if not expected_title:
        return resolved

    verifier = bind_handler("group.identity_matches")
    result = verifier({"group_jid": resolved.target, "expected_name": expected_title})
    if not isinstance(result, dict):
        raise ValueError("group.identity_matches returned a non-dict result")

    matched = bool(result.get("matched", False))
    detail = str(result.get("detail", "")).strip() or "no verification detail provided"
    return replace(
        resolved,
        verification_supported=True,
        live_identity_match=matched,
        live_identity={
            "expected_title": expected_title,
            "detail": detail,
        },
    )


def _verify_slack_identity(
    resolved: ResolvedContext,
    bind_handler: Any,
) -> ResolvedContext:
    if not resolved.target or not isinstance(resolved.target, str) or not resolved.target.startswith("C"):
        return resolved
    if not isinstance(resolved.expected_identity, dict):
        return resolved

    expected_name = str(resolved.expected_identity.get("name", "")).strip()
    if not expected_name:
        return resolved

    verifier = bind_handler("slack.channel_info")
    result = verifier({"channel_id": resolved.target, "expected_name": expected_name})
    if not isinstance(result, dict):
        raise ValueError("slack.channel_info returned a non-dict result")

    matched = bool(result.get("matched", False))
    detail = str(result.get("detail", "")).strip() or "no verification detail provided"
    return replace(
        resolved,
        verification_supported=True,
        live_identity_match=matched,
        live_identity={
            "expected_name": expected_name,
            "detail": detail,
        },
    )


def _verify_mailchimp_identity(
    resolved: ResolvedContext,
    bind_handler: Any,
) -> ResolvedContext:
    """Verify Mailchimp audience identity — deferred until handler registered."""
    if not resolved.target or not isinstance(resolved.target, str):
        return resolved
    if not isinstance(resolved.expected_identity, dict):
        return resolved

    expected_name = str(resolved.expected_identity.get("name", "")).strip()
    if not expected_name:
        return resolved

    return replace(
        resolved,
        verification_supported=False,
        live_identity_match=None,
        live_identity={"expected_name": expected_name, "detail": "mailchimp audience verification deferred"},
    )
