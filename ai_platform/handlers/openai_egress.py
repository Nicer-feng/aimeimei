from .shared import *
from .. import openai_egress as egress
from .. import openai_budget as budget


class OpenAIEgressHandlersMixin:
    def handle_admin_openai_budget(self):
        try:
            if self.command == 'GET':
                return self.json({'budget': budget.summary()})
            data = self.read_body(limit=4096)
            return self.json({'ok': True, 'budget': budget.configure(data)})
        except (ValueError, TypeError):
            return self.error(HTTPStatus.BAD_REQUEST, '请检查月度额度、开关和美元折算汇率')
        except (sqlite3.Error, budget.BudgetError):
            return self.error(HTTPStatus.SERVICE_UNAVAILABLE, 'OpenAI 额度配置暂不可用，请稍后重试')

    def handle_admin_openai_egress(self):
        if self.command == "GET":
            data = {"egress": egress.public_config(), "nodes": []}
            if data["egress"]["installed"]:
                try:
                    data["nodes"] = egress.nodes()
                except egress.EgressError as exc:
                    data["notice"] = exc.message
            return self.json(data)
        try:
            data = self.read_body(limit=16384)
            if not isinstance(data, dict):
                raise ValueError("invalid body")
            config = egress.configure(data, reload_subscription=bool(data.get("reload_subscription")))
            payload = {"ok": True, "egress": config, "nodes": []}
            if config["installed"]:
                try:
                    payload["nodes"] = egress.nodes()
                except egress.EgressError as exc:
                    payload["notice"] = exc.message
            return self.json(payload)
        except egress.EgressError as exc:
            return self.error(HTTPStatus.CONFLICT if exc.code == "busy" else HTTPStatus.BAD_REQUEST, exc.message)
        except (ValueError, OSError):
            return self.error(HTTPStatus.BAD_REQUEST, "代理配置保存失败，请检查配置与文件权限")

    def handle_admin_openai_test(self):
        try:
            data = self.read_body(limit=16384)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        if not isinstance(data, dict) or data.get("kind") not in ("proxy", "model"):
            return self.error(HTTPStatus.BAD_REQUEST, "invalid test kind")
        if data.get("kind") == "proxy":
            return self.json(egress.probe())
        model_id = str(data.get("model_id") or "")
        with db() as conn:
            row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone() if model_id else None
        model = dict(row) if row else {}
        for key in ("base_url", "model", "api_key"):
            if str(data.get(key) or "").strip():
                model[key] = str(data[key]).strip()
        if not egress.is_openai_url(model.get("base_url")) or not model.get("model"):
            return self.error(HTTPStatus.BAD_REQUEST, "请选择已配置的官方 OpenAI 模型或填写官方 Endpoint 与 Model")
        try:
            egress.validate_openai_url(str(model["base_url"]).rstrip("/") + "/models")
        except (ValueError, egress.EgressError):
            return self.error(HTTPStatus.BAD_REQUEST, "官方 API Base URL 应为 https://api.openai.com/v1")
        return self.json(egress.probe(model))

    def handle_model_availability(self):
        model_id = urlparse(self.path).path.split("/")[-2]
        with db() as conn:
            row = conn.execute("SELECT * FROM models WHERE id=? AND enabled=1", (model_id,)).fetchone()
        if not row:
            return self.error(HTTPStatus.NOT_FOUND, "model not found")
        if not egress.is_openai_url(row["base_url"]):
            return self.json({"model_id": model_id, "status": "not_applicable"})
        try:
            budget.check()
        except budget.BudgetError as exc:
            return self.json({"model_id": model_id, **egress.result("unavailable", exc.code, exc.message)})
        return self.json({"model_id": model_id, **egress.availability(row)})
