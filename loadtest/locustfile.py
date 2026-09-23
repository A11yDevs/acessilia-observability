"""Read-only AgentOS load scenario. Running agents is intentionally excluded."""

import os

from locust import HttpUser, between, task


class AgentOSReader(HttpUser):
    wait_time = between(1, 3)

    def headers(self):
        token = os.getenv("AGENTOS_TOKEN", "")
        return {"Authorization": f"Bearer {token}"} if token else {}

    @task(3)
    def agents(self):
        self.client.get("/agents", headers=self.headers(), name="GET /agents")

    @task
    def teams(self):
        self.client.get("/teams", headers=self.headers(), name="GET /teams")

    @task
    def workflows(self):
        self.client.get("/workflows", headers=self.headers(), name="GET /workflows")
