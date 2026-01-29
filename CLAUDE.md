### Development Practices
- Test Driven Development with failing tests first
- Makefile for all build/test/run commands
- Go modules for dependencies
- golangci-lint for code quality
- dbmate for migrations (Memgraph schema setup)
- Uber's dig for dependency injection
- Minimal functionality first, then add complexity
- Compile after each change, no compile errors allowed
- Run tests before any success reporting


## DETAILED WAY OF WORKING

- Start with minimal functionality and verify it works before adding complexity
- For all compiled languages please compile after each change.
- Do not leave code with compile errors.
- Once you are done making a change, kindly run linting and fix any errors.
- Follow Test Driven Development
   -  Make sure to add test cases before you make a change.
   -  Be kind and run a failing test, fix it and then run test again.
   -  commit when tests are passing.
- Please make sure to run tests before committing.
- Please make sure after Compilation and Linting that the tests are passing before reporting any success.
- Kindly avoid stating things like "it works", if you want to show, show me green tests.
- I cannot request this enough, please make sure to run tests after every change.
- I prefer trunk based development, and git for version control.
- Prefer latest version of libs unless there is a reason not to.
- Use dbmate when any table is added or changed.
- Use Makefile for all build commands