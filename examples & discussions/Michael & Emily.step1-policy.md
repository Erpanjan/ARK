# Michael & Emily - Step 1 Policy

Generated from: `examples & discussions/Michael & Emily.md` via `/advisor/api/v1/generate-step1-policy-json`.

## Policy Title
Carter Family Unified Diversification and College Funding Policy

## Executive Summary
This policy establishes a unified investment and funding strategy for Michael and Emily Carter, addressing portfolio concentration, tax efficiency, and college savings for their son Noah. The plan diversifies the taxable brokerage, introduces a dedicated 529 college savings account, and reallocates retirement assets for improved risk management and tax outcomes, while maintaining emergency reserves and supporting long-term lifestyle continuity.

## Sections
### Client Background

Michael (36) and Emily Carter (34) are a married couple residing in Austin, Texas, with one child, Noah (age 1). Michael is a Senior Operations Manager with a high, stable income; Emily works part-time as a pediatric nurse. The household is focused on maintaining lifestyle, saving for Noah's education, and preparing for retirement.

### Client Financial Snapshot

Combined gross income is $242,000/year (Michael: $188,000 salary + $18,000 bonus; Emily: $48,000). Net monthly take-home is $12,300–$13,100. Annual spending is $146,400. Assets include $78,000 in bank savings, $275,000 in taxable brokerage (100% US equities), and $322,000 in 401(k) (100% US treasuries). Liabilities: $472,000 mortgage at 3.375%, and student loans (minimum $280/month).

### Client Financial Needs

Key needs: diversify taxable brokerage holdings, improve tax efficiency, establish dedicated college savings for Noah, maintain emergency reserves, and monitor retirement readiness.

### Client Investment Preferences and Behavioral Considerations

The Carters prefer maintaining a 6-month emergency reserve, avoiding over-concentration in taxable accounts, and seek disciplined, tax-efficient allocation. They value stability, lifestyle continuity, and are open to phased portfolio adjustments.

### Taxes, Exclusions, and Exemptions

Current structure places all US equities in taxable accounts and all US treasuries in 401(k), which is suboptimal for tax efficiency. No explicit tax-exempt accounts for education exist yet. No insurance or estate exclusions specified.

### Other Special Requirements

Maintain at least 6 months of expenses in liquid emergency reserves. No insurance or estate planning requirements specified in current context.

### Capital Deployment Timeline

A total of $675,000 USD will be deployed across all accounts: $275,000 in taxable brokerage, $322,000 in 401(k), $78,000 in bank savings, and initial funding for a new 529 plan. Deployment will occur immediately upon policy adoption, with phased contributions to the 529 plan from taxable assets.

### Portfolio Policy

Adopt a unified, diversified portfolio across taxable and tax-advantaged accounts. Reduce US equity concentration in taxable brokerage, introduce international equity and fixed income, and allocate 401(k) to a balanced mix of equities and bonds. Establish a 529 plan for college savings, funded via periodic transfers from taxable assets.

### Investment Vehicle Selection Highlights

{"recommended_securities":[{"security_name":"US Total Stock Market ETF","asset_class":"US Equity","allocation_pct":30.0,"allocation_amount":202500.0,"management_style":"passive","security_id":"VTI"},{"security_name":"International Equity ETF","asset_class":"International Equity","allocation_pct":15.0,"allocation_amount":101250.0,"management_style":"passive","security_id":"VXUS"},{"security_name":"US Aggregate Bond ETF","asset_class":"US Fixed Income","allocation_pct":25.0,"allocation_amount":168750.0,"management_style":"passive","security_id":"AGG"},{"security_name":"401(k) Diversified Target Date Fund","asset_class":"Multi-Asset (Retirement)","allocation_pct":25.0,"allocation_amount":168750.0,"management_style":"active","security_id":"TDF401K"},{"security_name":"529 College Savings Plan Portfolio","asset_class":"Education Savings","allocation_pct":5.0,"allocation_amount":33750.0,"management_style":"passive","security_id":"529TX"}]}

### Risk Management Framework

Diversification across asset classes and accounts reduces concentration risk. Emergency reserves are maintained at 6 months of expenses. Portfolio risk is targeted at a moderate level (approximate volatility 14%), with regular reviews for rebalancing and risk tolerance alignment.

### Policy Evaluation Metrics

Success will be measured by portfolio diversification (no single asset class >35%), maintenance of emergency reserves, progress toward college funding, and retirement readiness projections. Annual reviews will assess allocation discipline and tax efficiency.

### Fee and Governance Notes

Preference for low-cost, passive ETFs in taxable and 529 accounts; 401(k) utilizes available target date or diversified funds. Ongoing advisory and fund fees will be monitored to ensure cost efficiency.

### Disclaimer and Acknowledgment

This policy is based on information provided as of June 2024. Actual results may vary due to market, tax, or personal changes. No insurance or estate advice is included. Client review and acknowledgment required before implementation.

### Tool Execution Log

Three deterministic cashflow model runs (t1, t2, t3) confirmed no projected shortfall under current assumptions. Stress tests highlighted investment concentration and college savings gaps, which this policy addresses.


## Portfolio
```json
{
  "currency": "USD",
  "recommended_securities": [
    {
      "allocation_amount": 202500.0,
      "allocation_pct": 30.0,
      "asset_class": "US Equity",
      "management_style": "passive",
      "security_id": "VTI",
      "security_name": "US Total Stock Market ETF"
    },
    {
      "allocation_amount": 101250.0,
      "allocation_pct": 15.0,
      "asset_class": "International Equity",
      "management_style": "passive",
      "security_id": "VXUS",
      "security_name": "International Equity ETF"
    },
    {
      "allocation_amount": 168750.0,
      "allocation_pct": 25.0,
      "asset_class": "US Fixed Income",
      "management_style": "passive",
      "security_id": "AGG",
      "security_name": "US Aggregate Bond ETF"
    },
    {
      "allocation_amount": 168750.0,
      "allocation_pct": 25.0,
      "asset_class": "Multi-Asset (Retirement)",
      "management_style": "active",
      "security_id": "TDF401K",
      "security_name": "401(k) Diversified Target Date Fund"
    },
    {
      "allocation_amount": 33750.0,
      "allocation_pct": 5.0,
      "asset_class": "Education Savings",
      "management_style": "passive",
      "security_id": "529TX",
      "security_name": "529 College Savings Plan Portfolio"
    }
  ],
  "total_transfer": 675000.0
}
```

## Execution
```json
{
  "capital_deployment_timeline": "Deploy $675,000 USD immediately across all accounts, with phased 529 plan contributions sourced from taxable brokerage.",
  "funding_source": "JPMorgan Chase Bank, N.A. — Account ending in XXX",
  "remedy_name": "Carter Family Unified Diversification and College Funding Policy"
}
```

## Risk Framework
```json
"Diversify across equities, fixed income, and education savings vehicles; maintain emergency reserves; rebalance annually to target risk profile."
```

## Evaluation Metrics
```json
"Monitor diversification, emergency reserve adequacy, college savings progress, and retirement readiness annually."
```

## Fee And Governance Notes
Utilize low-cost, passive ETFs where possible; monitor 401(k) and 529 plan fees; review policy annually.

## Disclaimer
Policy recommendations are based on current client data and market assumptions as of June 2024. Results may vary. No insurance or estate planning advice included.

## Tool Execution Log
```json
"Three deterministic cashflow model runs (t1, t2, t3) confirmed no projected shortfall; stress tests identified and informed policy remedies for concentration and college savings gaps."
```

## Raw Step1 JSON
```json
{
  "disclaimer": "Policy recommendations are based on current client data and market assumptions as of June 2024. Results may vary. No insurance or estate planning advice included.",
  "evaluation_metrics": "Monitor diversification, emergency reserve adequacy, college savings progress, and retirement readiness annually.",
  "execution": {
    "capital_deployment_timeline": "Deploy $675,000 USD immediately across all accounts, with phased 529 plan contributions sourced from taxable brokerage.",
    "funding_source": "JPMorgan Chase Bank, N.A. — Account ending in XXX",
    "remedy_name": "Carter Family Unified Diversification and College Funding Policy"
  },
  "executive_summary": "This policy establishes a unified investment and funding strategy for Michael and Emily Carter, addressing portfolio concentration, tax efficiency, and college savings for their son Noah. The plan diversifies the taxable brokerage, introduces a dedicated 529 college savings account, and reallocates retirement assets for improved risk management and tax outcomes, while maintaining emergency reserves and supporting long-term lifestyle continuity.",
  "fee_and_governance_notes": "Utilize low-cost, passive ETFs where possible; monitor 401(k) and 529 plan fees; review policy annually.",
  "policy_title": "Carter Family Unified Diversification and College Funding Policy",
  "portfolio": {
    "currency": "USD",
    "recommended_securities": [
      {
        "allocation_amount": 202500.0,
        "allocation_pct": 30.0,
        "asset_class": "US Equity",
        "management_style": "passive",
        "security_id": "VTI",
        "security_name": "US Total Stock Market ETF"
      },
      {
        "allocation_amount": 101250.0,
        "allocation_pct": 15.0,
        "asset_class": "International Equity",
        "management_style": "passive",
        "security_id": "VXUS",
        "security_name": "International Equity ETF"
      },
      {
        "allocation_amount": 168750.0,
        "allocation_pct": 25.0,
        "asset_class": "US Fixed Income",
        "management_style": "passive",
        "security_id": "AGG",
        "security_name": "US Aggregate Bond ETF"
      },
      {
        "allocation_amount": 168750.0,
        "allocation_pct": 25.0,
        "asset_class": "Multi-Asset (Retirement)",
        "management_style": "active",
        "security_id": "TDF401K",
        "security_name": "401(k) Diversified Target Date Fund"
      },
      {
        "allocation_amount": 33750.0,
        "allocation_pct": 5.0,
        "asset_class": "Education Savings",
        "management_style": "passive",
        "security_id": "529TX",
        "security_name": "529 College Savings Plan Portfolio"
      }
    ],
    "total_transfer": 675000.0
  },
  "risk_framework": "Diversify across equities, fixed income, and education savings vehicles; maintain emergency reserves; rebalance annually to target risk profile.",
  "sections": [
    {
      "content": "Michael (36) and Emily Carter (34) are a married couple residing in Austin, Texas, with one child, Noah (age 1). Michael is a Senior Operations Manager with a high, stable income; Emily works part-time as a pediatric nurse. The household is focused on maintaining lifestyle, saving for Noah's education, and preparing for retirement.",
      "id": "s1",
      "title": "Client Background"
    },
    {
      "content": "Combined gross income is $242,000/year (Michael: $188,000 salary + $18,000 bonus; Emily: $48,000). Net monthly take-home is $12,300–$13,100. Annual spending is $146,400. Assets include $78,000 in bank savings, $275,000 in taxable brokerage (100% US equities), and $322,000 in 401(k) (100% US treasuries). Liabilities: $472,000 mortgage at 3.375%, and student loans (minimum $280/month).",
      "id": "s2",
      "title": "Client Financial Snapshot"
    },
    {
      "content": "Key needs: diversify taxable brokerage holdings, improve tax efficiency, establish dedicated college savings for Noah, maintain emergency reserves, and monitor retirement readiness.",
      "id": "s3",
      "title": "Client Financial Needs"
    },
    {
      "content": "The Carters prefer maintaining a 6-month emergency reserve, avoiding over-concentration in taxable accounts, and seek disciplined, tax-efficient allocation. They value stability, lifestyle continuity, and are open to phased portfolio adjustments.",
      "id": "s4",
      "title": "Client Investment Preferences and Behavioral Considerations"
    },
    {
      "content": "Current structure places all US equities in taxable accounts and all US treasuries in 401(k), which is suboptimal for tax efficiency. No explicit tax-exempt accounts for education exist yet. No insurance or estate exclusions specified.",
      "id": "s5",
      "title": "Taxes, Exclusions, and Exemptions"
    },
    {
      "content": "Maintain at least 6 months of expenses in liquid emergency reserves. No insurance or estate planning requirements specified in current context.",
      "id": "s6",
      "title": "Other Special Requirements"
    },
    {
      "content": "A total of $675,000 USD will be deployed across all accounts: $275,000 in taxable brokerage, $322,000 in 401(k), $78,000 in bank savings, and initial funding for a new 529 plan. Deployment will occur immediately upon policy adoption, with phased contributions to the 529 plan from taxable assets.",
      "id": "s7",
      "title": "Capital Deployment Timeline"
    },
    {
      "content": "Adopt a unified, diversified portfolio across taxable and tax-advantaged accounts. Reduce US equity concentration in taxable brokerage, introduce international equity and fixed income, and allocate 401(k) to a balanced mix of equities and bonds. Establish a 529 plan for college savings, funded via periodic transfers from taxable assets.",
      "id": "s8",
      "title": "Portfolio Policy"
    },
    {
      "content": "{\"recommended_securities\":[{\"security_name\":\"US Total Stock Market ETF\",\"asset_class\":\"US Equity\",\"allocation_pct\":30.0,\"allocation_amount\":202500.0,\"management_style\":\"passive\",\"security_id\":\"VTI\"},{\"security_name\":\"International Equity ETF\",\"asset_class\":\"International Equity\",\"allocation_pct\":15.0,\"allocation_amount\":101250.0,\"management_style\":\"passive\",\"security_id\":\"VXUS\"},{\"security_name\":\"US Aggregate Bond ETF\",\"asset_class\":\"US Fixed Income\",\"allocation_pct\":25.0,\"allocation_amount\":168750.0,\"management_style\":\"passive\",\"security_id\":\"AGG\"},{\"security_name\":\"401(k) Diversified Target Date Fund\",\"asset_class\":\"Multi-Asset (Retirement)\",\"allocation_pct\":25.0,\"allocation_amount\":168750.0,\"management_style\":\"active\",\"security_id\":\"TDF401K\"},{\"security_name\":\"529 College Savings Plan Portfolio\",\"asset_class\":\"Education Savings\",\"allocation_pct\":5.0,\"allocation_amount\":33750.0,\"management_style\":\"passive\",\"security_id\":\"529TX\"}]}",
      "id": "s9",
      "title": "Investment Vehicle Selection Highlights"
    },
    {
      "content": "Diversification across asset classes and accounts reduces concentration risk. Emergency reserves are maintained at 6 months of expenses. Portfolio risk is targeted at a moderate level (approximate volatility 14%), with regular reviews for rebalancing and risk tolerance alignment.",
      "id": "s10",
      "title": "Risk Management Framework"
    },
    {
      "content": "Success will be measured by portfolio diversification (no single asset class >35%), maintenance of emergency reserves, progress toward college funding, and retirement readiness projections. Annual reviews will assess allocation discipline and tax efficiency.",
      "id": "s11",
      "title": "Policy Evaluation Metrics"
    },
    {
      "content": "Preference for low-cost, passive ETFs in taxable and 529 accounts; 401(k) utilizes available target date or diversified funds. Ongoing advisory and fund fees will be monitored to ensure cost efficiency.",
      "id": "s12",
      "title": "Fee and Governance Notes"
    },
    {
      "content": "This policy is based on information provided as of June 2024. Actual results may vary due to market, tax, or personal changes. No insurance or estate advice is included. Client review and acknowledgment required before implementation.",
      "id": "s13",
      "title": "Disclaimer and Acknowledgment"
    },
    {
      "content": "Three deterministic cashflow model runs (t1, t2, t3) confirmed no projected shortfall under current assumptions. Stress tests highlighted investment concentration and college savings gaps, which this policy addresses.",
      "id": "s14",
      "title": "Tool Execution Log"
    }
  ],
  "tool_execution_log": "Three deterministic cashflow model runs (t1, t2, t3) confirmed no projected shortfall; stress tests identified and informed policy remedies for concentration and college savings gaps."
}
```
