# D9 text-claim eval set: draft for review

**82 Ugandan claims in English: 40 true, 42 false.** Data:
`data/fact-checks/eval-text/uganda-text-claims-draft.json` (every row `review: pending`).

Every claim can be judged from text: none describes a photo or video. Strike, fix or relabel rows;
when it's approved I set `review: approved` and run the blind eval on it.

## How it was built

- **False, from AFP (30):** Ugandan AFP fact-checks where the claim itself is false (it didn't
  happen, or the statement was invented), not a true event with a wrong picture. Reworded as
  the claim someone would paste. AFP's own headline and verdict are in the Note.
- **True, researched (29):** each checked on 31 Oct 2026 against the linked report.
- **True, hand-curated (11):** the 2026 claims already checked for the seed corpus.
- **False, perturbed (12):** a checked fact with one detail changed (a number, place or year).
  None repeats a true claim's topic, so the duplicate check can't copy one verdict to the other.

## Before it runs

- **Keep the answer key out:** the 30 AFP items are in Zuula's seed corpus (85 Ugandan AFP
  reports), so the eval database must not seed them, and the blind mode already drops afp.com
  search results. The 11 hand-curated true claims are seeded too, so the same applies.
- **Turn duplicate reuse off for the run:** a few pairs are close in wording (the 2021 and
  2026 swearing-in; the 2026 result, true at 71 % and false at 51 %). With reuse on, the
  second could copy the first one's verdict. The harness needs a switch for this.
- **Dates matter:** "true" means true as of the date given. Claims about the present
  ("Facebook has been blocked", "close to two million refugees") can go stale.
- Only English for now; Luganda and other languages would need the same claims translated.

## False claims from AFP fact-checks

| # | Claim | Category | Source | Note |
|---|---|---|---|---|
| 1 | Canada has cancelled the sale of Bombardier planes to Uganda Airlines | Economy | [source](https://factcheck.afp.com/canadas-bombardier-did-not-renege-sale-4-airplanes-uganda-airlines) | Canada’s Bombardier did not renege on the sale of 4 airplanes to Uganda Airlines |
| 2 | Uganda's Ministry of Finance is giving business grants to entrepreneurs who apply online | Economy | [source](https://factcheck.afp.com/ugandans-ignore-scam-business-grant-application-it-isnt-finance-ministry) | Ugandans: Ignore this scam ‘business grant application’, it isn’t from the finance ministry |
| 3 | Guinness World Records has named Kizza Besigye the world's most arrested man | Politics | [source](https://factcheck.afp.com/no-such-title-has-been-bestowed-kizza-besigye-guinness-world-records) | No such title has been bestowed on Kizza Besigye by Guinness World Records |
| 4 | President Museveni has postponed the 2021 elections because of the coronavirus | Elections | [source](https://factcheck.afp.com/ugandan-president-has-not-announced-elections-postponement-officials-dismiss-claim) | Ugandan president has not announced elections postponement; officials dismiss claim |
| 5 | The governments of Uganda and Kenya have told landlords to stop collecting rent during the coronavirus outbreak | Economy | [source](https://factcheck.afp.com/ugandan-and-kenyan-authorities-reject-claims-they-told-landlords-stop-rent-collection) | Ugandan and Kenyan authorities reject claims that they told landlords to stop rent collection |
| 6 | Joe Biden and Barack Obama tweeted "Free Bobi Wine" after his arrest in November 2020 | Politics | [source](https://factcheck.afp.com/hoax-tweets-falsely-claim-support-biden-obama-ugandan-presidential-challenger) | Hoax tweets falsely claim support from Biden, Obama for Ugandan ... |
| 7 | The United States is evacuating its citizens from Uganda | Politics | [source](https://factcheck.afp.com/letter-claiming-united-states-evacuating-its-citizens-uganda-old-hoax) | Letter claiming United States is evacuating its citizens from Uganda is an old hoax |
| 8 | Police spokesperson Fred Enanga said Bobi Wine is planning violence | Politics | [source](https://factcheck.afp.com/account-impersonating-ugandan-police-spokesman-spreads-baseless-claims-about-opposition-leader) | Account impersonating Ugandan police spokesman spreads baseless claims about opposition leader |
| 9 | Uganda's national Covid-19 task force is recruiting staff through a Facebook job advert | Health | [source](https://factcheck.afp.com/facebook-account-impersonating-ugandan-newspaper-promotes-fabricated-job-listings) | Facebook account impersonating Ugandan newspaper promotes fabricated job listings |
| 10 | General Muhoozi Kainerugaba tweeted a threat against the Buganda Kingdom | Politics | [source](https://factcheck.afp.com/fabricated-tweet-falsely-claims-musevenis-son-threatened-buganda-kingdom) | Fabricated tweet falsely claims Museveni’s son threatened Buganda Kingdom |
| 11 | Bobi Wine will be sworn in as Uganda's president in May 2021 | Elections | [source](https://factcheck.afp.com/fabricated-screenshots-news-broadcasts-used-spread-false-claims-about-ugandan-presidential) | Fabricated screenshots of news broadcasts used to spread false claims about Ugandan presidential inauguration |
| 12 | The European Union wrote to Bobi Wine warning him against holding his own swearing-in ceremony | Politics | [source](https://factcheck.afp.com/european-union-dismisses-hoax-letter-purporting-warn-ugandan-opposition-leader-over-inauguration) | European Union dismisses hoax letter purporting to warn Ugandan opposition leader over inauguration event |
| 13 | President Museveni collapsed and was airlifted to a hospital in Germany in July 2021 | Politics | [source](https://factcheck.afp.com/doc.afp.com.9DY74E) | There is no evidence that Ugandan President Yoweri Museveni has been admitted to the hospital |
| 14 | A bomb exploded at the state funeral of a Ugandan military commander in September 2021 | Politics | [source](https://factcheck.afp.com/doc.afp.com.9LZ9ZX) | Bomb plot foiled but no explosion before state funeral for Ugandan military commander |
| 15 | A continental poll has named Museveni Africa's most loved president | Politics | [source](https://factcheck.afp.com/doc.afp.com.9LY483) | Newspaper front page doctored with false poll report about Ugandan leader Yoweri Museveni |
| 16 | China has taken over Entebbe International Airport and renamed it | Economy | [source](https://factcheck.afp.com/doc.afp.com.9TQ3RC) | AFP photo of Entebbe International Airport digitally altered amid rumours of a Chinese takeover |
| 17 | Entebbe International Airport has been renamed HUEN Airport | Society | [source](https://factcheck.afp.com/doc.afp.com.323T7XJ) | Name of Uganda's Entebbe International Airport has not been changed to HUEN |
| 18 | Fuel in Uganda sells at three times the price it sells for in Kenya | Economy | [source](https://factcheck.afp.com/doc.afp.com.328K32F) | Fuel shortage crisis in Kenya sparks online disinformation |
| 19 | There is no Ebola outbreak in Uganda; the 2022 outbreak is a hoax | Health | [source](https://factcheck.afp.com/doc.afp.com.32MC2QJ) | Conspiracy theories denying Ebola outbreak in Uganda shared online |
| 20 | The International Criminal Court has issued an arrest warrant for President Museveni over war crimes | Politics | [source](https://factcheck.afp.com/doc.afp.com.33A72J8) | Ugandan YouTubers spread disinformation with clickbait headlines |
| 21 | Uganda's Anti-Homosexuality Bill became law in February 2023 | Politics | [source](https://factcheck.afp.com/doc.afp.com.33AX362) | Posts falsely claimed tough anti-gay bill in Uganda had become law by February 2023 |
| 22 | Entebbe International Airport is facing closure after failing an international audit | Society | [source](https://factcheck.afp.com/doc.afp.com.33JP6BZ) | TikTok video falsely claims Entebbe Airport faces closure over purported audit |
| 23 | President Yoweri Museveni died in June 2023 | Politics | [source](https://factcheck.afp.com/doc.afp.com.33JZ8MR) | Online posts falsely announce Ugandan President Yoweri Museveni’s death |
| 24 | President Museveni has appointed his daughter Governor of the Bank of Uganda | Economy | [source](https://factcheck.afp.com/doc.afp.com.34PJ2XJ) | Posts falsely claim Ugandan President Yoweri Museveni’s daughter is new central bank governor |
| 25 | The US ambassador handed President Museveni a letter of apology from the United States | Politics | [source](https://factcheck.afp.com/doc.afp.com.36JP8GL) | Posts falsely claim US ambassador apologised to Ugandan president |
| 26 | Museveni announced that the 2026 election would be his last presidential bid | Elections | [source](https://factcheck.afp.com/doc.afp.com.74XF264) | Video of Uganda's Yoweri Museveni saying 2026 presidential bid will be his last is doctored |
| 27 | Museveni warned CNN journalist Larry Madowo over his coverage of Uganda's 2026 election | Elections | [source](https://factcheck.afp.com/doc.afp.com.86GG8ZR) | Video of Uganda’s Yoweri Museveni warning CNN journalist on election coverage is doctored |
| 28 | Uganda's health minister has declared an outbreak of Nipah virus in Uganda | Health | [source](https://factcheck.afp.com/doc.afp.com.97DC8KE) | Old Ebola video resurfaces in posts falsely claiming outbreak of Nipah virus in Uganda |
| 29 | President Museveni closed all schools in 2026 because of Ebola | Education | [source](https://factcheck.afp.com/doc.afp.com.B9HL3T3) | Video of Ugandan leader announcing school closures linked to Covid-19 pandemic, not Ebola |
| 30 | Police seized the former Speaker's designer dress in a corruption raid | Politics | [source](https://factcheck.afp.com/doc.afp.com.B7HU9ZQ) | AI-generated clip falsely links Ugandan politician’s designer outfit to corruption raid |

## True claims, researched

| # | Claim | Category | Source | Note |
|---|---|---|---|---|
| 31 | Uganda Airlines received its first two Bombardier CRJ900 jets in April 2019 | Economy | [source](https://www.africanews.com/amp/2019/04/24/uganda-airlines-gets-first-planes/) |  |
| 32 | Under the Parish Development Model, each parish receives 100 million shillings a year | Economy | [source](https://www.mediacentre.go.ug/node/1066) |  |
| 33 | Kizza Besigye was seized in Nairobi in November 2024 and charged before a military court in Kampala | Politics | [source](https://www.monitor.co.ug/uganda/news/national/why-besigye-was-abducted-in-nairobi-remanded-in-kampala--4830012) |  |
| 34 | The Electoral Commission banned mass rallies for the 2021 campaign because of Covid-19 | Elections | [source](https://eagle.co.ug/2020/06/16/covid-19-ec-bans-mass-rallies-a-head-of-2021-elections/) |  |
| 35 | President Museveni closed all schools in March 2020 because of the coronavirus | Education | [source](https://www.monitor.co.ug/uganda/news/national/museveni-orders-closure-of-schools-suspends-religious-gatherings-over-coronavirus-1881126) |  |
| 36 | At least 54 people were killed in the protests after Bobi Wine's arrest in Luuka in November 2020 | Politics | [source](https://ugandaradionetwork.net/story/compensate-families-of-victims-killed-in-2020-riots-mpuuga-) |  |
| 37 | The World Bank suspended new public financing to Uganda in August 2023 over the Anti-Homosexuality Act | Economy | [source](https://www.aljazeera.com/economy/2023/8/9/world-bank-halts-new-loans-to-uganda-over-anti-lgbtq-law) |  |
| 38 | Uganda imposed a 42-day lockdown in June 2021 during a second wave of Covid-19 | Health | [source](https://www.citizen.digital/news/uganda-starts-42-day-covid-19-lockdown-following-a-surge-in-cases-12006403) |  |
| 39 | Museveni was sworn in for a sixth term at Kololo on 12 May 2021 | Politics | [source](https://www.aljazeera.com/news/2021/5/12/ugandas-president-museveni-sworn-in-for-sixth-term) |  |
| 40 | The Electoral Commission declared Museveni winner of the 2021 presidential election with about 58.6 percent | Elections | [source](https://nation.africa/kenya/news/africa/uganda-elections-museveni-declared-winner-with-58-6pc-votes-3259258) |  |
| 41 | Deputy Inspector General of Police Paul Lokech died in August 2021 | Politics | [source](https://www.monitor.co.ug/uganda/news/national/deputy-igp-maj-gen-paul-lokech-dead--3519594) |  |
| 42 | Uganda borrowed from China's Exim Bank in 2015 to upgrade and expand Entebbe International Airport | Economy | [source](https://www.theeastafrican.co.ke/tea/business/how-uganda-coughed-up-entebbe-airport-to-china-3631398) |  |
| 43 | Uganda Airlines began direct flights between Entebbe and London Gatwick in May 2025 | Economy | [source](https://www.tourismupdate.com/article/uganda-airlines-gatwick-service-takes-off) |  |
| 44 | Uganda declared an outbreak of Sudan Ebola virus in Mubende district in September 2022 | Health | [source](https://uganda.un.org/en/204930-ebola-response-plan-un-uganda-september-2022-march-2023) |  |
| 45 | The International Criminal Court convicted former LRA commander Dominic Ongwen of 61 crimes in February 2021 | Politics | [source](https://www.aljazeera.com/news/2021/2/4/icc-finds-ugandan-lra-commander-guilty-of-war-crimes) |  |
| 46 | Museveni signed the Anti-Homosexuality Act into law in May 2023 | Politics | [source](https://www.monitor.co.ug/uganda/news/national/museveni-signs-tougher-anti-homosexuality-bill-into-law-4250416) |  |
| 47 | Uganda's Constitutional Court upheld most of the Anti-Homosexuality Act in April 2024 | Politics | [source](https://www.hrw.org/news/2024/04/04/uganda-court-upholds-anti-homosexuality-act) |  |
| 48 | The United States imposed visa restrictions on Ugandan officials over the 2021 election | Politics | [source](https://www.aljazeera.com/news/2021/4/16/us-slaps-visa-bans-on-ugandan-officials-linked-to-disputed-polls) |  |
| 49 | A Ugandan nurse who died in Kampala in January 2025 was confirmed to have Sudan Ebola virus | Health | [source](https://www.aljazeera.com/amp/news/2025/1/30/uganda-confirms-one-person-dead-in-ebola-outbreak) |  |
| 50 | The East African Crude Oil Pipeline runs about 1,443 km from Hoima in Uganda to Tanga in Tanzania | Economy | [source](https://www.engineeringnews.co.za/article/east-african-crude-oil-pipeline-ugandatanzania-2023-11-17) |  |
| 51 | At least 30 people died when the Kiteezi landfill collapsed in August 2024 | Society | [source](https://monitor.co.ug/uganda/news/national/six-more-bodies-recovered-as-kiteezi-landfill-collapse-death-toll-reaches-30-4725370) |  |
| 52 | Uganda hosted the Non-Aligned Movement summit in Kampala in January 2024 | Politics | [source](https://www.theeastafrican.co.ke/tea/business/kampala-hosts-non-aligned-movement-summit-4492612) |  |
| 53 | Uganda's first satellite, PearlAfricaSat-1, was launched in November 2022 | Technology | [source](https://www.theeastafrican.co.ke/tea/news/east-africa/uganda-launches-first-satellite-into-space-4012454) |  |
| 54 | Joshua Cheptegei won the 10,000 metres gold medal at the Paris 2024 Olympics | Sport | [source](https://nbssport.co.ug/article/paris-2024-gold-olympic-record-for-cheptegei-in-mens-10000m) |  |
| 55 | Parliament passed a bill in November 2024 dissolving the Uganda Coffee Development Authority | Economy | [source](https://independent.co.ug/parliament-passes-national-coffee-bill) |  |
| 56 | Facebook has been blocked in Uganda since the January 2021 election | Technology | [source](https://www.bloomberg.com/news/articles/2021-01-22/uganda-to-maintain-facebook-ban-indefinitely-new-vision-says) |  |
| 57 | Uganda hosts close to two million refugees, the largest refugee population in Africa | Society | [source](https://www.unhcr.org/news/press-releases/nearly-2-million-refugees-risk-uganda-emergency-funds-dwindle-and-services-cut) |  |
| 58 | Uganda's coffee exports earned more than 1 billion dollars in the 2023/24 financial year | Economy | [source](https://www.capitalfm.co.ke/business/2024/07/ugandas-coffee-export-earnings-reach-30-year-high) |  |
| 59 | Museveni signed a law in June 2025 allowing military courts to try some civilians | Politics | [source](https://eagle.co.ug/2025/06/16/court-martial-back-as-museveni-signs-updf-amendment-bill-2025-into-law/) |  |

## True claims, hand-curated (already in the seed corpus)

| # | Claim | Category | Source | Note |
|---|---|---|---|---|
| 60 | Uganda's Ministry of Health confirmed three new Ebola cases on 23 May 2026, raising the country's total confirmed infections to five | Health | [source](https://www.the-star.co.ke/news/africa/2026-05-23-uganda-confirms-three-new-ebola-cases) |  |
| 61 | Uganda's Ministry of Health declared the 2026 Ebola outbreak over in late July 2026, after 20 confirmed cases | Health | [source](https://atta.travel/resource/ebola-update-uganda-declares-end-of-2026-ebola-outbreak.html) |  |
| 62 | Uganda's Electoral Commission declared Yoweri Museveni the winner of the January 2026 presidential election, with about 71.6% of the vote | Politics | [source](https://www.primebusiness.africa/museveni-declared-winner-of-ugandas-presidential-election-amid-opposition-rejection/) |  |
| 63 | Yoweri Museveni was sworn in for a seventh presidential term on 12 May 2026 at Kololo Independence Grounds | Politics | [source](https://nbssport.co.ug/article/first-lady-janet-museveni-peter-ogwang-keep-sports-docket-in-new-cabinet) |  |
| 64 | Uganda's annual headline inflation rose to 4.0% in July 2026, up from 3.7% in June | Economy | [source](https://www.monitor.co.ug/uganda/news/national/bank-of-uganda-holds-benchmark-rate-at-9-75-as-inflation-edge-prompts-caution-5557436) |  |
| 65 | The Bank of Uganda held its Central Bank Rate at 9.75% on 13 August 2026 | Economy | [source](https://www.monitor.co.ug/uganda/news/national/bank-of-uganda-holds-benchmark-rate-at-9-75-as-inflation-edge-prompts-caution-5557436) |  |
| 66 | Uganda's Communications Commission ordered a nationwide shutdown of public internet access starting 6pm on 13 January 2026, ahead of the presidential election | Technology | [source](https://www.dignited.com/119463/uganda-communications-commission-ucc-orders-temporary-internet-shutdown-ahead-of-2026-presidential-election/) |  |
| 67 | Starlink disabled its satellite internet service in Uganda effective 1 January 2026, after a UCC directive over unlicensed operation | Technology | [source](https://techafricanews.com/2026/01/05/starlink-shuts-down-satellite-internet-services-in-uganda-following-regulatory-directive/) |  |
| 68 | Uganda signed a civil-works contract with Japan's Zenitaka Corporation on 10 July 2026 to build a new Karuma Bridge | Infrastructure | [source](https://www.zawya.com/en/economy/africa/uganda-secures-funding-for-new-karuma-bridge-394071) |  |
| 69 | Uganda's coffee sector recorded its best year on record between May 2024 and April 2025, exporting 7.17 million 60-kg bags worth $1.97 billion | Economy | [source](https://www.foodbusinessmea.com/?p=2146043) |  |
| 70 | Uganda's UNEB scheduled the release of 2025 UACE (A-Level) results for 13 March 2026 at a State House Nakasero ceremony | Education | [source](https://www.pulse.ug/story/uneb-2025-uace-results-out-today-2026031305234929163) |  |

## False claims made by changing one detail

| # | Claim | Category | Source | Note |
|---|---|---|---|---|
| 71 | Uganda's 2024 national census counted about 60 million people | Society | [source](https://www.monitor.co.ug/uganda/news/national/uganda-s-population-now-at-45-9m-people-says-ubos-4671332) | In fact: 45.9 million (UBOS, 2024). |
| 72 | The ADF attack on Lhubiriha Secondary School in Mpondwe in June 2023 killed five people | Education | [source](https://www.aljazeera.com/amp/news/2023/6/17/dozens-killed-in-attack-on-ugandan-school-near-drc-border) | In fact: at least 41 killed. |
| 73 | Uganda's social media tax, introduced in July 2018, charged users 2,000 shillings a day | Technology | [source](https://www.aljazeera.com/amp/economy/2018/7/1/uganda-introduces-social-media-tax-despite-criticism) | In fact: 200 shillings a day. |
| 74 | Muhoozi Kainerugaba was appointed Uganda's Chief of Defence Forces in 2019 | Politics | [source](https://citizen.digital/article/president-museveni-appoints-his-son-as-chief-of-defence-forces-n338953) | In fact: appointed March 2024. |
| 75 | Speaker Jacob Oulanyah died in a Nairobi hospital in March 2022 | Politics | [source](https://www.monitor.co.ug/uganda/news/national/speaker-jacob-oulanyah-dies-in-seattle-3754188) | In fact: died in Seattle. |
| 76 | Bank of Uganda Governor Emmanuel Tumusiime-Mutebile died in London in January 2022 | Economy | [source](https://www.monitor.co.ug/uganda/news/national/bank-of-uganda-governor-emmanuel-tumusiime-mutebile-dies-in-nairobi-3691090) | In fact: died in Nairobi. |
| 77 | Uganda reopened all schools in January 2021 after the Covid-19 closure | Education | [source](https://www.aljazeera.com/news/2022/1/10/ugandan-children-back-to-school-after-nearly-2-year-covid-closure) | In fact: reopened 10 January 2022. |
| 78 | Uganda will co-host the 2027 Africa Cup of Nations with Rwanda and Burundi | Sport | [source](https://www.theeastafrican.co.ke/tea/sports/caf-awards-kenya-uganda-tanzania-2027-afcon-rights-4381990) | In fact: co-hosts are Kenya and Tanzania. |
| 79 | Museveni was declared winner of the January 2026 election with 51 percent of the vote | Elections | [source](https://en.wikipedia.org/wiki/2026_Ugandan_general_election) | In fact: 71.65 percent. |
| 80 | Peruth Chemutai won Uganda's first ever Olympic gold medal at the Tokyo 2020 Games | Sport | [source](https://www.anocolympic.org/noc-highlights/uganda-secures-first-womens-olympic-gold-medal) | In fact: first Ugandan woman to win an Olympic medal; Uganda had won gold before (1972, 2012). |
| 81 | Parliament removed the presidential age limit of 75 years in 2005 | Politics | [source](https://www.aljazeera.com/news/2018/1/2/uganda-enacts-law-ending-presidential-age-limits) | In fact: removed in December 2017. |
| 82 | The East African Crude Oil Pipeline will carry Ugandan oil to the Kenyan port of Mombasa | Economy | [source](https://eacop.com/?p=918) | In fact: it runs to Tanga, Tanzania. |
