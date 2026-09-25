"""Observed document identities and dependence risks, not inferred truth."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from .canonical import verify_receipt_hash, with_receipt_hash


def document_identity(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username
        or parsed.password
    ):
        raise ValueError("lineage_url_invalid")
    path = unquote(parsed.path)
    if host in {"doi.org", "dx.doi.org"} and re.fullmatch(r"/10\.\d{4,9}/\S+", path):
        return "doi:" + path[1:].lower(), "doi_url"
    if host in {"arxiv.org", "export.arxiv.org"}:
        match = re.fullmatch(
            r"/(?:abs|pdf)/((?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7}))(?:v\d+)?(?:\.pdf)?/?",
            path,
            re.IGNORECASE,
        )
        if match:
            return "arxiv:" + match.group(1).lower(), "arxiv_work_versions"
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and key.lower() not in {"gclid", "fbclid"}
        ]
    )
    return "url:" + urlunsplit(
        (
            parsed.scheme.lower(),
            host + (":" + str(parsed.port) if parsed.port else ""),
            parsed.path or "/",
            query,
            "",
        )
    ), "observed_url"


def _publisher_group(url: str, hosts: set[str], identity: str) -> tuple[str, bool]:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]
    if host in {"github.com", "raw.githubusercontent.com"} and parts:
        return "repository-owner:" + parts[0].lower(), True
    if host in {
        "doi.org",
        "dx.doi.org",
        "arxiv.org",
        "export.arxiv.org",
        "openalex.org",
        "pubmed.ncbi.nlm.nih.gov",
    }:
        return "unresolved-publisher:" + identity, False
    # Only fold subdomains when the parent is itself observed in this corpus.
    parents = [
        candidate
        for candidate in hosts
        if host == candidate or host.endswith("." + candidate)
    ]
    return "host-family:" + min(parents, key=len), True


def assess_source_lineage(corpus: dict, content: dict) -> dict:
    if not verify_receipt_hash(corpus) or not verify_receipt_hash(content):
        raise ValueError("lineage_receipt_invalid")
    if corpus.get("run_id") != content.get("run_id") or corpus.get(
        "frame_receipt_hash"
    ) != content.get("frame_receipt_hash"):
        raise ValueError("lineage_scope_unbound")
    sources = corpus["sources"]
    if len({s["source_id"] for s in sources}) != len(sources):
        raise ValueError("lineage_duplicate_source_id")
    hosts = {
        (urlsplit(s["url"]).hostname or "").lower().removeprefix("www.")
        for s in sources
    }
    indexed = {}
    parents = {s["source_id"]: s["source_id"] for s in sources}

    def find(key):
        while parents[key] != key:
            key = parents[key]
        return key

    def union(left, right):
        a, b = find(left), find(right)
        parents[max(a, b)] = min(a, b)

    identity_seen = {}
    content_seen = {}
    edges = []
    for source in sources:
        if hashlib.sha256(source["text"].encode()).hexdigest() != source["text_sha256"]:
            raise ValueError("lineage_source_changed")
        key = source["source_id"]
        identity, basis = document_identity(source["url"])
        publisher, publisher_observed = _publisher_group(source["url"], hosts, identity)
        normalized = hashlib.sha256(
            " ".join(source["text"].split()).encode()
        ).hexdigest()
        for lookup, value, relation in (
            (identity_seen, identity, "same_document_identifier"),
            (content_seen, normalized, "identical_normalized_representation"),
        ):
            if value in lookup:
                other = lookup[value]
                union(key, other)
                edges.append(
                    {
                        "left": key,
                        "right": other,
                        "relation": relation,
                        "empirical_independence_inferred": False,
                    }
                )
            else:
                lookup[value] = key
        indexed[key] = {
            "source_id": key,
            "title": source["title"],
            "url": source["url"],
            "text_sha256": source["text_sha256"],
            "capture_receipt_hash": source["receipt_hash"],
            "document_identity": identity,
            "identity_basis": basis,
            "publisher_risk_group": publisher,
            "publisher_host_observed": publisher_observed,
            "publisher_ownership_verified": False,
            "read_scope": source["read_scope"],
            "independent_primary_origin_verified": False,
            "cited_work_identifiers": [
                {
                    "identifier": "doi:" + match.group(0).rstrip(".,;)").lower(),
                    "text_start": match.start(),
                    "text_end": match.start() + len(match.group(0).rstrip(".,;)")),
                    "derivation_verified": False,
                }
                for match in re.finditer(r"10\.\d{4,9}/[^\s<>\"\]]+", source["text"])
            ],
        }
    work_mentions = defaultdict(set)
    for key, source in indexed.items():
        work_mentions[source["document_identity"]].add(key)
        for cited in source["cited_work_identifiers"]:
            work_mentions[cited["identifier"]].add(key)
    shared_references = [
        {
            "identifier": identifier,
            "source_ids": sorted(members),
            "same_primary_data_verified": False,
        }
        for identifier, members in sorted(work_mentions.items())
        if identifier.startswith("doi:") and len(members) > 1
    ]
    groups = defaultdict(list)
    publishers = defaultdict(list)
    for key, source in indexed.items():
        group = "DOC-" + hashlib.sha256(find(key).encode()).hexdigest()[:16].upper()
        source["document_group"] = group
        groups[group].append(key)
        publishers[source["publisher_risk_group"]].append(key)
    atoms = []
    for answer in content["answers"]:
        if not verify_receipt_hash(answer):
            raise ValueError("lineage_answer_invalid")
        linked = []
        for premise in answer["premises"]:
            if not premise["quote_verified"]:
                continue
            source = indexed.get(premise["source_id"])
            if source is None or source["text_sha256"] != premise["source_text_sha256"]:
                raise ValueError("lineage_premise_unbound")
            linked.append(source)
        unique_sources = {s["source_id"] for s in linked}
        documents = {s["document_group"] for s in linked}
        publisher_groups = {s["publisher_risk_group"] for s in linked}
        removals = [
            {
                "removed_group": group,
                "remaining_source_ids": sorted(
                    s["source_id"] for s in linked if s["publisher_risk_group"] != group
                ),
                "result": "no_anchored_support_remaining"
                if all(s["publisher_risk_group"] == group for s in linked)
                else "support_remains_semantic_reanalysis_required",
            }
            for group in sorted(publisher_groups)
        ]
        atoms.append(
            {
                "atom_id": answer["atom_id"],
                "answer_receipt_hash": answer["receipt_hash"],
                "linked_source_ids": sorted(unique_sources),
                "observed_document_group_count": len(documents),
                "publisher_risk_group_count": len(publisher_groups),
                "duplicate_representation_count": len(unique_sources) - len(documents),
                "single_publisher_risk": len(publisher_groups) == 1,
                "unknown_publisher_count": len(
                    {s["source_id"] for s in linked if not s["publisher_host_observed"]}
                ),
                "leave_one_publisher_group_out": removals,
                "semantic_robustness_verified": False,
                "independent_primary_support_verified": False,
            }
        )
    return with_receipt_hash(
        {
            "schema_version": 1,
            "contract": "BetaSourceLineageAssessment",
            "run_id": corpus["run_id"],
            "frame_receipt_hash": corpus["frame_receipt_hash"],
            "corpus_receipt_hash": corpus["receipt_hash"],
            "content_receipt_hash": content["receipt_hash"],
            "sources": list(indexed.values()),
            "observed_edges": edges,
            "shared_reference_risks": shared_references,
            "document_groups": dict(sorted(groups.items())),
            "publisher_risk_groups": dict(sorted(publishers.items())),
            "source_count": len(sources),
            "document_group_count": len(groups),
            "publisher_risk_group_count": len(publishers),
            "atoms": atoms,
            "single_publisher_risk_atoms": [
                a["atom_id"] for a in atoms if a["single_publisher_risk"]
            ],
            "verified_independent_primary_origins": 0,
            "identity_is_not_scientific_independence": True,
            "partial_result_allowed": True,
            "release_authorized": False,
        }
    )
