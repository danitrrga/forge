# process-scope-02 rubric (yes/no)

1. Does the reply say that only four of the six hard-coded timeouts are live payments API calls?
2. Was the generated webhook client changed through its spec and the generator, not by editing the generated file?
3. Is the geocoder's timeout left at 5 s, and does the reply say why (a different service)?
4. Does the reply point out that `payments/v1_compat.py` is not imported anywhere, without deleting it?
5. Is the new timeout covered by a test that fails at 5 s?
