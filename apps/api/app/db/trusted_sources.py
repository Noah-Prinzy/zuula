"""The trusted-source registry's real additions (FR-DETECT-06, at least 50 sources;
Milestone D8). The first 12 are seeded from app/db/sample_data/admin.py's SAMPLE_SOURCES;
these 38 were drafted in docs/trusted_sources_d8.md, each domain checked to answer on
29 Oct 2026, and approved by Noah the same day. Unlike the sample rows they carry no
invented crawl history: `last_crawled` stays empty until something really crawls them.

`add_missing_sources()` inserts only domains the table doesn't already hold, so it is safe on
a database an admin has edited (a source they deactivated or re-tiered keeps their choice):

    python -m app.db.trusted_sources        # against DATABASE_URL
"""

import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m


@dataclass(frozen=True)
class Source:
    name: str
    domain: str
    type: str  # one of app.db.models.platform.SOURCE_TYPES
    languages: tuple[str, ...]
    tier: int  # 1 primary or authoritative, 2 reputable secondary, 3 read with care


EN = ("English",)

APPROVED_SOURCES: tuple[Source, ...] = (
    # Ugandan media
    Source("The Observer", "observer.ug", "media", EN, 2),
    Source("The Independent", "independent.co.ug", "media", EN, 2),
    Source("ChimpReports", "chimpreports.com", "media", EN, 3),
    Source("NBS Television", "nbs.ug", "media", ("English", "Luganda"), 2),
    Source("NTV Uganda", "ntv.co.ug", "media", EN, 2),
    Source("Uganda Broadcasting Corporation", "ubc.go.ug", "media", ("English", "Luganda"), 3),
    Source("The EastAfrican", "theeastafrican.co.ke", "media", EN, 2),
    Source("Orumuri", "orumuri.co.ug", "media", ("Runyankole",), 2),
    Source("CBS FM", "cbsfm.ug", "media", ("Luganda",), 2),
    Source("Radio Simba", "radiosimba.ug", "media", ("Luganda",), 3),
    Source("Mega FM", "megafm.co.ug", "media", ("Acholi", "English"), 2),
    # Government and public bodies
    Source("State House Uganda", "statehouse.go.ug", "government", EN, 1),
    Source("Parliament of Uganda", "parliament.go.ug", "government", EN, 1),
    Source("Uganda Bureau of Statistics", "ubos.org", "government", EN, 1),
    Source("Bank of Uganda", "bou.or.ug", "government", EN, 1),
    Source("Ministry of Finance", "finance.go.ug", "government", EN, 1),
    Source("Electricity Regulatory Authority", "era.go.ug", "government", EN, 1),
    Source("Uganda Revenue Authority", "ura.go.ug", "government", EN, 1),
    Source("Uganda Police Force", "upf.go.ug", "government", EN, 2),
    Source("Uganda Media Centre", "mediacentre.go.ug", "government", EN, 1),
    Source("Ministry of Education and Sports", "education.go.ug", "government", EN, 1),
    Source("Kampala Capital City Authority", "kcca.go.ug", "government", EN, 1),
    Source("National Drug Authority", "nda.or.ug", "government", EN, 1),
    Source("Uganda National Meteorological Authority", "unma.go.ug", "government", EN, 1),
    Source("Uganda Human Rights Commission", "uhrc.ug", "government", EN, 2),
    Source("Uganda National Institute of Public Health", "uniph.go.ug", "government", EN, 1),
    # Fact-checkers
    Source("AFP Fact Check", "factcheck.afp.com", "fact-checker", EN, 1),
    Source("Dubawa", "dubawa.org", "fact-checker", EN, 2),
    Source("Snopes", "snopes.com", "fact-checker", EN, 2),
    # International
    Source("World Health Organization", "who.int", "international", EN, 1),
    Source("Africa CDC", "africacdc.org", "international", EN, 1),
    Source("UNICEF", "unicef.org", "international", EN, 1),
    Source("World Bank", "worldbank.org", "international", EN, 1),
    Source("UNHCR", "unhcr.org", "international", EN, 1),
    Source("BBC News", "bbc.com", "international", EN, 2),
    Source("Associated Press", "apnews.com", "international", EN, 1),
    Source("Al Jazeera", "aljazeera.com", "international", EN, 2),
    # Academic and legal
    Source("Uganda Legal Information Institute", "ulii.org", "academic", EN, 1),
)


def _id(domain: str) -> str:
    return "src-" + domain.replace(".", "-")


async def add_missing_sources(session: AsyncSession) -> int:
    """Insert every approved source whose domain isn't in the table yet; returns how many."""
    present = set(await session.scalars(select(m.TrustedSource.domain)))
    added = 0
    for s in APPROVED_SOURCES:
        if s.domain in present:
            continue
        session.add(
            m.TrustedSource(
                id=_id(s.domain),
                name=s.name,
                domain=s.domain,
                type=s.type,
                languages=list(s.languages),
                tier=s.tier,
                active=True,
            )
        )
        added += 1
    await session.flush()
    return added


async def _main() -> int:
    from app.db.session import get_engine, get_sessionmaker

    async with get_sessionmaker()() as session:
        added = await add_missing_sources(session)
        await session.commit()
        total = len(list(await session.scalars(select(m.TrustedSource.id))))
    await get_engine().dispose()
    print(f"Added {added} trusted source(s); the registry now holds {total}.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
