from build import supervisors

TSINGHUA = "I99065089"


def au(aid, corr=False, lineage=(TSINGHUA,)):
    return {"author": {"id": "https://openalex.org/" + aid, "display_name": aid, "orcid": None},
            "is_corresponding": corr,
            "institutions": [{"lineage": ["https://openalex.org/" + i for i in lineage]}]}


def test_supervisors():
    # student first, corresponding author in the middle, last author: both supervisors count
    w = {"authorships": [au("A1"), au("A2", corr=True), au("A3")]}
    assert [s[0] for s in supervisors(w, TSINGHUA)] == ["A2", "A3"]
    # last author from another university is not this university's supervisor
    w = {"authorships": [au("A1"), au("A3", lineage=("I20231570",))]}
    assert supervisors(w, TSINGHUA) == []
    # corresponding and last author are the same person: counted once
    w = {"authorships": [au("A1"), au("A3", corr=True)]}
    assert len(supervisors(w, TSINGHUA)) == 1
    # consortium paper is skipped
    assert supervisors({"authorships": [au(f"A{i}") for i in range(40)]}, TSINGHUA) == []


if __name__ == "__main__":
    test_supervisors()
    print("ok")
