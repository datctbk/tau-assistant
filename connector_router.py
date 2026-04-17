from __future__ import annotations

from dataclasses import dataclass, field

from connectors import Connector, ConnectorRequest, ConnectorResponse


@dataclass
class ConnectorRouter:
    connectors: dict[str, Connector] = field(default_factory=dict)

    def register(self, connector: Connector) -> None:
        self.connectors[connector.name] = connector

    def has(self, connector_name: str) -> bool:
        return connector_name in self.connectors

    def route(self, connector_name: str, action: str, payload: dict[str, object] | None = None) -> ConnectorResponse:
        if connector_name not in self.connectors:
            return ConnectorResponse(ok=False, error=f"Unknown connector {connector_name!r}")
        req = ConnectorRequest(action=action, payload=payload or {})
        return self.connectors[connector_name].handle(req)
