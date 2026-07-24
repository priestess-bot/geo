"""Prompt Program application errors and command result contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from geo_core.prompts.program import (
    ProgramBinding,
    ProgramReleaseState,
    ProgramTestEvidence,
    PromptProgram,
    PromptProgramRelease,
)


_ResultT = TypeVar("_ResultT")


class PromptProgramApplicationError(RuntimeError):
    """Base application error safe to translate at a future transport boundary."""


class PromptProgramForbidden(PromptProgramApplicationError):
    """The principal lacks the required project role or approval separation."""


class PromptProgramNotFound(PromptProgramApplicationError):
    """A project-scoped Program, Release or binding is not visible."""


class PromptProgramRuntimeBlocked(PromptProgramApplicationError):
    """A runtime attempted to use an unfrozen or inconsistent binding."""


@dataclass(frozen=True)
class CommandReceipt(Generic[_ResultT]):
    value: _ResultT
    replayed: bool


@dataclass(frozen=True)
class CreatedPromptProgram:
    program: PromptProgram
    release: PromptProgramRelease
    state: ProgramReleaseState


@dataclass(frozen=True)
class CreatedPromptRelease:
    release: PromptProgramRelease
    state: ProgramReleaseState


@dataclass(frozen=True)
class TestedPromptProgram:
    release: PromptProgramRelease
    state: ProgramReleaseState
    evidence: ProgramTestEvidence


@dataclass(frozen=True)
class TransitionedPromptProgram:
    release: PromptProgramRelease
    state: ProgramReleaseState
    admitted_test_evidence: ProgramTestEvidence | None = None


@dataclass(frozen=True)
class BoundPromptProgram:
    release: PromptProgramRelease
    state: ProgramReleaseState
    binding: ProgramBinding


@dataclass(frozen=True)
class RuntimePromptProgram:
    release: PromptProgramRelease
    state: ProgramReleaseState
    binding: ProgramBinding
