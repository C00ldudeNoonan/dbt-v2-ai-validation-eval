from harness.score import false_positive_summary


def _run(arm, rep, flagged, fault="CONTROL"):
    return {"variant_id": "t__CONTROL", "fault_id": fault, "arm": arm, "repetition": str(rep),
            "flagged_any": str(flagged), "recon_queries_executed": "10", "recon_queries_flagged": "1" if flagged else "0"}


def _adj(rep, label, arm="C"):
    return {"variant_id": "t__CONTROL", "fault_id": "CONTROL", "arm": arm, "repetition": str(rep),
            "layer": "L3", "label": label}


def test_fp_rate_withheld_until_fully_labeled():
    runs = [_run("C", 1, True), _run("C", 2, False), _run("C", 3, True)]
    s = false_positive_summary(runs, [_adj(1, "noise"), _adj(3, "")])
    assert s["unlabeled"] == 1 and s["per_arm"]["C"]["fp_rate"] is None
    assert s["per_arm"]["C"]["flagged_runs"] == 2


def test_true_issue_flags_are_not_false_positives():
    runs = [_run("C", 1, True), _run("C", 2, False), _run("C", 3, True)]
    s = false_positive_summary(runs, [_adj(1, "noise"), _adj(3, "true_issue")])
    c = s["per_arm"]["C"]
    assert s["unlabeled"] == 0 and c["fp_runs"] == 1 and c["true_issue_runs"] == 1
    assert abs(c["fp_rate"] - 1 / 3) < 1e-9
