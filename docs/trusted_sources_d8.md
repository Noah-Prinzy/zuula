# Trusted sources: draft for Milestone D8 (for Noah's approval)

FR-DETECT-06 asks for at least 50 source databases. The registry has 12 (bottom table); these
38 bring it to 50. Each domain was checked on 29 Oct 2026 and answered over HTTPS; "blocks bots"
means it answered 403 to an automated request (the site exists, it just refuses scripts).

**What being on the list does:** the search tries these domains first and only widens to the
open web when they give too little, and citations from them are marked "Trusted". Subdomains
count (`who.int` covers `afro.who.int`). Tier is shown to admins; nothing ranks by it yet.
Tier 1 = primary or authoritative, 2 = reputable secondary, 3 = useful but read with care.

Approve, strike or add rows, then I seed them (locally, then production with your go-ahead).

## Ugandan media (11)

| Name | Domain | Languages | Tier | Note |
|---|---|---|---|---|
| The Observer | observer.ug | English | 2 | |
| The Independent | independent.co.ug | English | 2 | |
| ChimpReports | chimpreports.com | English | 3 | Fast, uneven sourcing |
| NBS Television | nbs.ug | English, Luganda | 2 | |
| NTV Uganda | ntv.co.ug | English | 2 | Nation Media Group |
| Uganda Broadcasting Corporation | ubc.go.ug | English, Luganda | 3 | State broadcaster: official positions |
| The EastAfrican | theeastafrican.co.ke | English | 2 | Regional weekly; blocks bots |
| Orumuri | orumuri.co.ug | Runyankole | 2 | New Vision group's Runyankole paper |
| CBS FM | cbsfm.ug | Luganda | 2 | Buganda kingdom radio |
| Radio Simba | radiosimba.ug | Luganda | 3 | |
| Mega FM | megafm.co.ug | Acholi, English | 2 | Gulu |

## Government and public bodies (15)

| Name | Domain | Languages | Tier | Note |
|---|---|---|---|---|
| State House Uganda | statehouse.go.ug | English | 1 | What the President said or signed |
| Parliament of Uganda | parliament.go.ug | English | 1 | Bills, Hansard |
| Uganda Bureau of Statistics | ubos.org | English | 1 | |
| Bank of Uganda | bou.or.ug | English | 1 | |
| Ministry of Finance | finance.go.ug | English | 1 | Budgets, taxes |
| Electricity Regulatory Authority | era.go.ug | English | 1 | Power tariffs |
| Uganda Revenue Authority | ura.go.ug | English | 1 | |
| Uganda Police Force | upf.go.ug | English | 2 | |
| Uganda Media Centre | mediacentre.go.ug | English | 1 | Government statements |
| Ministry of Education and Sports | education.go.ug | English | 1 | |
| Kampala Capital City Authority | kcca.go.ug | English | 1 | |
| National Drug Authority | nda.or.ug | English | 1 | Fake or banned medicines; blocks bots |
| Uganda National Meteorological Authority | unma.go.ug | English | 1 | |
| Uganda Human Rights Commission | uhrc.ug | English | 2 | |
| Uganda National Institute of Public Health | uniph.go.ug | English | 1 | Outbreak bulletins |

## Fact-checkers (3)

| Name | Domain | Languages | Tier | Note |
|---|---|---|---|---|
| AFP Fact Check | factcheck.afp.com | English | 1 | Source of the 363 real reports; blocks bots |
| Dubawa | dubawa.org | English | 2 | West Africa |
| Snopes | snopes.com | English | 2 | Global viral hoaxes |

## International (8)

| Name | Domain | Languages | Tier | Note |
|---|---|---|---|---|
| World Health Organization | who.int | English | 1 | Includes afro.who.int |
| Africa CDC | africacdc.org | English | 1 | |
| UNICEF | unicef.org | English | 1 | |
| World Bank | worldbank.org | English | 1 | |
| UNHCR | unhcr.org | English | 1 | Refugee figures; blocks bots |
| BBC News | bbc.com | English | 2 | |
| Associated Press | apnews.com | English | 1 | Blocks bots |
| Al Jazeera | aljazeera.com | English | 2 | |

## Academic and legal (1)

| Name | Domain | Languages | Tier | Note |
|---|---|---|---|---|
| Uganda Legal Information Institute | ulii.org | English | 1 | Laws and judgments |

## Already in the registry (12)

New Vision, Daily Monitor, Bukedde, Nile Post, Uganda Radio Network, Ministry of Health,
Electoral Commission, Uganda Communications Commission, Africa Check, PesaCheck, Reuters,
Makerere University AI Lab (air.ug).

## Gaps and choices to make

- **Ateso:** no Ateso-language outlet with a working website was found (New Vision's Etop
  has no site of its own). Acholi and Runyankole have one each.
- **Left out:** `uvri.go.ug` (Uganda Virus Research Institute) and `unra.go.ug` didn't answer
  at all (UNRA has been folded into the Ministry of Works); `gou.go.ug` answered 503;
  Chapter Four Uganda (civil society) doesn't fit any of the five types the registry allows.
- **State-owned outlets** (UBC, and Vision Group's papers) are good for what officials said,
  less so for whether it's true; UBC is tier 3 for that reason.
