"""Build professors.json: Computer Science supervisors at CSC host universities, from OpenAlex.

A supervisor here = the corresponding or last author of a recent CS paper (journal article or
conference paper) whose affiliation on that paper is the university.

    python build.py                # all universities in data/csc_universities.csv
    python build.py 10003 10699    # only these agency codes (handy for testing)

Without OPENALEX_API_KEY you share a $0.10/day budget (~1000 calls) with your whole network;
a free key from https://openalex.org/settings/api gives $1/day. The full build needs more than
1000 calls, but every finished university-year is cached in cache/, so just run it again.
"""
import csv, datetime, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from collections import Counter

YEARS = (2024, 2025, 2026)
MIN_PAPERS = 3     # ponytail: plain threshold, a student who leads 3+ papers slips in; raise it if lists look noisy
MAX_AUTHORS = 30   # big-consortium papers: the last author there is not a supervisor
KEY = os.environ.get("OPENALEX_API_KEY", "")
sys.stdout.reconfigure(errors="replace")


def get(params):
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params) + (f"&api_key={KEY}" if KEY else "")
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            wait = int(e.headers.get("Retry-After") or 2 ** attempt)
            if e.code in (401, 402, 403) or (e.code == 429 and wait > 60):
                raise Stop(f"OpenAlex said {e.code}: daily budget used up or key problem.")
            if e.code != 429 and e.code < 500:
                raise
            time.sleep(wait)
        except urllib.error.URLError:
            time.sleep(2 ** attempt)
    raise Stop("OpenAlex is not answering.")


class Stop(Exception):
    pass


def supervisors(work, oid):
    """[(author_id, name, orcid)] for the corresponding/last authors affiliated with university oid."""
    a = work["authorships"]
    if not a or len(a) > MAX_AUTHORS:
        return []
    url = "https://openalex.org/" + oid
    out = {}
    for i, x in enumerate(a):
        if x["author"]["id"] and (x["is_corresponding"] or i == len(a) - 1) and any(url in inst.get("lineage", []) for inst in x["institutions"]):
            out[x["author"]["id"].rsplit("/", 1)[1]] = (x["author"]["display_name"], x["author"]["orcid"])
    return [(k, n, o) for k, (n, o) in out.items()]


def fetch(oid, year):
    """Compact records of one university's CS papers in one year, cached in cache/."""
    path = f"cache/{oid}_{year}.json"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    flt = f"authorships.institutions.lineage:{oid},primary_topic.field.id:17,publication_year:{year},type:article|conference-paper"
    recs, page = [], 1
    while True:
        d = get({"filter": flt, "per_page": 200, "page": page,
                 "select": "id,doi,title,publication_year,cited_by_count,primary_topic,authorships"})
        for w in d["results"]:
            if sup := supervisors(w, oid):
                t = w["primary_topic"]
                recs.append([w["title"], year, w["doi"] or w["id"], w["cited_by_count"],
                             t["subfield"]["display_name"], t["display_name"], sup])
        if page * 200 >= min(d["meta"]["count"], 10000) or not d["results"]:
            break
        page += 1
    if d["meta"]["count"] > 10000:  # page= stops at 10k results; nobody is near that per year yet
        print(f"  warning: {oid} {year} has {d['meta']['count']} papers, only the first 10000 used")
    os.makedirs("cache", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False)
    return recs


def main():
    with open("data/csc_universities.csv", encoding="utf-8") as f:
        unis = list(csv.DictReader(f))
    only = set(sys.argv[1:])
    people = {}
    for ui, u in enumerate(unis):
        if only and u["agency_code"] not in only:
            continue
        try:
            recs = [r for y in YEARS for r in fetch(u["openalex_id"], y)]
        except Stop as e:  # write what we have so the site stays usable; the next run resumes from cache/
            print(f"{e} Stopped at {u['name']}. Run again later to continue.")
            break
        for title, year, url, cites, sub, topic, sup in recs:
            for aid, name, orcid in sup:
                # OpenAlex sometimes splits one person into several ids; a shared ORCID joins them back.
                # Names use U+2010 hyphens ("Shi‐Min Hu"), which nobody can type into a search box.
                p = people.setdefault(orcid or aid, {"id": aid, "name": name.replace("\N{HYPHEN}", "-"),
                                                     "orcid": orcid, "uni": Counter(), "subs": Counter(),
                                                     "topics": Counter(), "cites": 0, "papers": []})
                p["uni"][ui] += 1; p["subs"][sub] += 1; p["topics"][topic] += 1; p["cites"] += cites
                p["papers"].append((year, cites, title, url))
        print(f"[{ui + 1}/{len(unis)}] {u['name']}: {len(recs)} papers with a supervisor found", flush=True)

    profs = []
    for p in people.values():
        if len(p["papers"]) < MIN_PAPERS:
            continue
        p["papers"].sort(key=lambda x: (x[0], x[1]), reverse=True)
        profs.append({"id": p["id"], "name": p["name"], "orcid": p["orcid"], "uni": p["uni"].most_common(1)[0][0],
                      "papers": len(p["papers"]), "cites": p["cites"],
                      "fields": [s for s, _ in p["subs"].most_common(2)],
                      "topics": [t for t, _ in p["topics"].most_common(3)],
                      "recent": [[t, y, url] for y, c, t, url in p["papers"][:2]]})
    profs.sort(key=lambda p: -p["papers"])
    # Paper titles are most of the bytes, so they go in papers.json (same order), which the page loads
    # after it is already usable. Field and topic names repeat a lot, so professors store list indexes.
    papers = [p.pop("recent") for p in profs]
    fields = sorted({f for p in profs for f in p["fields"]})
    topics = sorted({t for p in profs for t in p["topics"]})
    fi, ti = {f: i for i, f in enumerate(fields)}, {t: i for i, t in enumerate(topics)}
    for p in profs:
        p["fields"] = [fi[f] for f in p["fields"]]
        p["topics"] = [ti[t] for t in p["topics"]]
    out = {"generated": datetime.date.today().isoformat(), "years": YEARS,
           "universities": [{k: u[k] for k in ("name", "city", "province", "tags", "agency_code")} for u in unis],
           "fields": fields, "topics": topics, "professors": profs}
    for path, data in (("professors.json", out), ("papers.json", papers)):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(profs)} supervisors written to professors.json and papers.json")


if __name__ == "__main__":
    main()
