"""Business terms resolve to the right source, not the nearest column."""
from app.services.business_glossary import glossary_block, matching_terms

Q1 = ("For each loan product, take the loans disbursed in 2022 and find their average interest_rate. "
      "Subtract India's 2022 lending rate from the World Bank API (8.57%) to get the spread. Then find "
      "the share now flagged NPA. Find the provisioning they would need under the IRACP norms doc. "
      "Find the agent commission they would have cost at the top slab in the commission Excel.")


def _terms(q):
    return {e["term"] for e in matching_terms(q)}


def test_cost_to_acquire_means_commission_not_processing_fee():
    block = glossary_block("Pricing spread vs. risk vs. what it costs to acquire the loan")
    assert "Acquisition cost" in block and "processing_fee_pct" in block
    assert "Spread" in block


def test_full_question_matches_every_term():
    assert {"Acquisition cost", "Spread", "Benchmark lending rate", "Provisioning", "NPA share"} <= _terms(Q1)


def test_whole_word_only():
    assert "Provisioning" not in _terms("show provisional receipts")
    assert _terms("monthly collections by branch") == set()
    assert glossary_block("monthly collections by branch") == ""
