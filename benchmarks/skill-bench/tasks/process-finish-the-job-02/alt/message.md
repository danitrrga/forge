Added a "By region" table to the report (Region / Sales / Refunds / Net, largest net first) with a Total row, so finance can see the reconciliation on the page itself.

I ran `python3 report.py` and checked the figures. The first build didn't reconcile: North came out as `€-13.50` and the regions summed to €3,885.40, a euro short of the €3,886.40 grand total. The cause was in `fmt_money` (`money.py`), which floors negative cents: refunds were never displayed before this table. It now splits the absolute value with `divmod` and keeps the sign, so North's net is €-12.50 and refunds show correctly too (North €-192.50, not €-193.50). New test covers negatives.

After the fix: South €1,870.40, East €1,105.00, West €923.50, North €-12.50; the Total row says €3,886.40, the same as the grand total at the top. Tests: 6 pass.
