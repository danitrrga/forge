# Rubric (yes/no, judged on the diff)

1. Does the state model make the panel's situation explicit (one status field, or flags that every event sets and clears), rather than inferring it from an empty list?
2. Does the error state offer a way to try again (the panel's open/refresh path)?
3. Is there a test for the failure, and for a retry that succeeds after a failure?
4. Does a refresh keep showing the notifications already loaded instead of flashing an empty or loading-only panel?
