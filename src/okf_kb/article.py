"""The article model shared by the index generator and the read-side commands.

An article is a markdown file with OKF frontmatter. The index generator renders
it, and the graph and search commands read it, so the model lives here, below
all three, and none of them has to import another's module for it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from okf_kb import frontmatter as fm

if TYPE_CHECKING:
    from pathlib import Path

#: The generated index filename, and one of the OKF reserved names.
INDEX_FILENAME = "INDEX.md"

#: Emoji prefixing an article entry when its title carries none of its own.
DEFAULT_ARTICLE_EMOJI = "📄"

#: OKF §5.2 trust tiers, in increasing order of assurance.
TIER_UNVERIFIED = "unverified"
TIER_MACHINE = "machine-confirmed"
TIER_HUMAN = "human-reviewed"

#: The lifecycle status that needs no badge, being the assumed default.
DEFAULT_STATUS = "stable"

#: The OKF actor prefix that marks a human sign-off (§7).
_HUMAN_ACTOR_PREFIX = "human:"


def split_emoji(title: str, default: str = DEFAULT_ARTICLE_EMOJI) -> tuple[str, str]:
    """Separate a leading emoji from a title.

    Several articles encode their icon in the frontmatter ``title`` itself
    (``"🏁 CAR-bench Challenge — Project Hub"``). The index renders the icon in
    the bullet rather than inside the link text, so it has to come back off.

    Args:
        title: The raw title.
        default: Emoji to return when the title carries none.

    Returns:
        A tuple of ``(emoji, remaining title)``. The title is returned unchanged
        when its first word is ordinary text.

    """
    stripped = title.strip()
    head, _, rest = stripped.partition(" ")
    if rest.strip() and head and not any(ch.isalnum() for ch in head):
        return head, rest.strip()
    return default, stripped


def trust_tier(frontmatter: fm.Frontmatter) -> str:
    """Derive an article's OKF §5.2 trust tier.

    Args:
        frontmatter: The article's parsed frontmatter.

    Returns:
        :data:`TIER_UNVERIFIED` when no ``verified`` record is present,
        :data:`TIER_HUMAN` when any recorded actor is a ``human:`` id, and
        :data:`TIER_MACHINE` otherwise. An empty or null ``verified`` value
        counts as unverified: it attests to nothing.

    """
    verified = frontmatter.get("verified")
    if not verified:
        return TIER_UNVERIFIED
    if any(actor.startswith(_HUMAN_ACTOR_PREFIX) for actor in _actor_strings(verified)):
        return TIER_HUMAN
    return TIER_MACHINE


def _actor_strings(value: Any) -> list[str]:  # noqa: ANN401
    """Collect every string nested anywhere inside a ``verified`` value.

    OKF leaves the ``verified`` shape open — a bare actor id, a list of ids, or
    a list of mappings with ``by`` and ``at`` are all seen in the wild. Rather
    than guess, every leaf string is inspected for the ``human:`` prefix.

    Args:
        value: The raw ``verified`` value.

    Returns:
        Every string leaf, in traversal order.

    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _actor_strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _actor_strings(item)]
    return []


@dataclass(frozen=True)
class Article:
    """An article as the index needs to see it.

    Attributes:
        path: Absolute path to the article.
        rel: POSIX path relative to the wiki root.
        frontmatter: The article's parsed frontmatter.

    """

    path: Path
    rel: str
    frontmatter: fm.Frontmatter

    @property
    def title(self) -> str:
        """The display title, with any leading emoji removed."""
        return split_emoji(self._raw_title)[1]

    @property
    def emoji(self) -> str:
        """The bullet emoji: the title's own, or the default."""
        return split_emoji(self._raw_title)[0]

    @property
    def _raw_title(self) -> str:
        declared = self.frontmatter.get("title")
        if isinstance(declared, str) and declared.strip():
            return declared
        return self.path.stem

    @property
    def description(self) -> str:
        """The one-line summary, or an empty string when undeclared."""
        declared = self.frontmatter.get("description")
        return declared.strip() if isinstance(declared, str) else ""

    @property
    def date_added(self) -> dt.date | None:
        """The date the article entered the wiki, if declared."""
        return fm.as_date(self.frontmatter.get("date_added"))

    @property
    def tags(self) -> list[str]:
        """Declared tags, as strings."""
        tags = self.frontmatter.get("tags")
        if not isinstance(tags, list):
            return []
        return [str(tag) for tag in tags]

    @property
    def status(self) -> str:
        """The lifecycle status, defaulting to ``stable``."""
        status = self.frontmatter.get("status")
        if isinstance(status, str) and status.strip():
            return status.strip()
        return DEFAULT_STATUS

    @property
    def source_resources(self) -> list[str]:
        """Repo-relative paths of the article's declared sources."""
        return fm.source_resources(self.frontmatter)

    @property
    def tier(self) -> str:
        """The OKF §5.2 trust tier."""
        return trust_tier(self.frontmatter)

    @property
    def sort_key(self) -> tuple[dt.date, str]:
        """Sort oldest first, then by filename, matching the curated order."""
        return (self.date_added or dt.date.min, self.path.name)
