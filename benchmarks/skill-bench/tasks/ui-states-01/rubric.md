# Rubric (yes/no, judged on the diff)

1. Is the failure told apart from "no orders" where it happens (the API client), instead of being guessed in the view from an empty list?
2. Does a new test cover the service being down or answering with an error?
3. Does the error message tell the customer their orders could not be loaded and that they can try again, without showing status codes or exception text?
4. Does a customer who really has no orders still see the existing empty state?
