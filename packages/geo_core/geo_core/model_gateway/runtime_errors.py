"""Typed runtime-catalog failures used for fail-closed recovery branching."""

from geo_core.model_gateway.ports import ModelCallPersistenceError


class ModelCallJobAdmissionNotFound(ModelCallPersistenceError):
    """The project-scoped Durable Job has no Model Gateway admission yet."""


__all__ = ["ModelCallJobAdmissionNotFound"]
