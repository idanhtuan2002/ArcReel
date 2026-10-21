"""Public-key authenticated, content-free manual publication discovery."""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import TypeAdapter

from r2.advanced_creative.digests import canonical_json_bytes
from r2.contracts.opportunity import Slug
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.manual_admission import PublicationHeader, PublicationReceiptMetadata, SealExpectation
from server.services.m9_manual_authenticity import verify_manual_seal, verify_publication_receipt

_KEY_ID = TypeAdapter(Slug)
_OPEN_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


@dataclass(frozen=True, slots=True, kw_only=True)
class ManualSealVerifier:
    """Host-composed verifier without a signing callback or private-key material."""

    public_key: bytes = field(repr=False)
    verification_key_id: str

    def __post_init__(self) -> None:
        try:
            _KEY_ID.validate_python(self.verification_key_id, strict=True)
            if type(self.public_key) is not bytes or len(self.public_key) != 32:
                raise ValueError("invalid host public key")
        except (ValueError, TypeError):
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE) from None

    def verify_material(self, raw_seal: bytes, actual_bytes: bytes, *, expected: SealExpectation) -> None:
        if expected.verification_key_id != self.verification_key_id:
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        verify_manual_seal(raw_seal, actual_bytes, public_key=self.public_key, expected=expected)

    def verify_receipt(self, raw_receipt: bytes, *, expected: PublicationReceiptMetadata) -> PublicationHeader:
        if expected.verification_key_id != self.verification_key_id:
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        return verify_publication_receipt(raw_receipt, public_key=self.public_key, expected=expected)


@dataclass(frozen=True, slots=True)
class FileManualPublicationStore:
    """Discover signed original refs without opening content or extending its clocks."""

    root: Path
    user_id: str = field(kw_only=True)
    project_name: str = field(kw_only=True)
    verifier: ManualSealVerifier = field(kw_only=True)

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.absolute())

    async def lookup_receipt(self, publication_key: str) -> PublicationHeader | None:
        return await asyncio.to_thread(self._lookup_receipt, publication_key)

    def _lookup_receipt(self, publication_key: object) -> PublicationHeader | None:
        directory = descriptor = -1
        try:
            if not isinstance(publication_key, str) or not publication_key or len(publication_key) > 4096:
                raise ValueError("invalid publication identity")
            name = hashlib.sha256(publication_key.encode()).hexdigest() + ".json"
            scope = hashlib.sha256(
                canonical_json_bytes({"user_id": self.user_id, "project_name": self.project_name})
            ).hexdigest()
            # Open every ancestor separately: O_NOFOLLOW on the final root alone misses parent symlinks.
            directory = os.open(self.root.anchor, _OPEN_DIRECTORY)
            for component in (*self.root.parts[1:], "manual-publications", scope, "headers"):
                next_directory = os.open(component, _OPEN_DIRECTORY, dir_fd=directory)
                os.close(directory)
                directory = next_directory
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("publication header must be a regular file")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                raw = stream.read(65_537)
            if not 0 < len(raw) <= 65_536:
                raise ValueError("publication header exceeds bound")
            candidate = PublicationHeader.model_validate_json(raw)
            metadata = candidate.metadata
            if (metadata.context.user_id, metadata.context.project_name, metadata.publication_key) != (
                self.user_id,
                self.project_name,
                publication_key,
            ):
                raise ValueError("publication header identity differs")
            return self.verifier.verify_receipt(raw, expected=metadata)
        except FileNotFoundError:
            return None
        except OpportunityError:
            raise
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH) from None
        finally:
            for opened in (descriptor, directory):
                if opened >= 0:
                    os.close(opened)
