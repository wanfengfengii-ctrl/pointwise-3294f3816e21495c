"""Run this project's full unittest suite from the repository root.

The suite holds the original regressions and the limited-row disclosure tests.
After it passes, the same entry point runs the disclosure fixture end to end
(V1 and V2) so a broken proof or rejection path still exits non-zero.
"""
import sys
import unittest


def run_suite():
    suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
    if suite.countTestCases():
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    else:
        print('No tests discovered in tests/', file=sys.stderr)
        result = unittest.TestResult()
    for status, failed_cases in (
        ('FAIL', (test for test, _ in result.failures)),
        ('ERROR', (test for test, _ in result.errors)),
        ('UNEXPECTED_SUCCESS', result.unexpectedSuccesses),
    ):
        for test in failed_cases:
            print(f'{status} {test.id()}')
    successful = result.testsRun > 0 and result.wasSuccessful()
    print(f'TEST SUMMARY total={result.testsRun} failures={len(result.failures)} '
          f'errors={len(result.errors)} skipped={len(result.skipped)} '
          f'expected_failures={len(result.expectedFailures)} '
          f'unexpected_successes={len(result.unexpectedSuccesses)} '
          f'result={"PASS" if successful else "FAIL"}')
    return successful


def run_fixtures():
    import contextlib
    import io
    import disclosure_fixture
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            disclosure_fixture.main()
            disclosure_fixture.main_v2()
    except Exception as exc:  # noqa: BLE001 - report any fixture failure
        print(f'FIXTURE FAIL {type(exc).__name__}: {exc}', file=sys.stderr)
        return False
    print('FIXTURE SUMMARY v1=PASS v2=PASS')
    return True


def main():
    suite_ok = run_suite()
    fixtures_ok = run_fixtures()
    return 0 if suite_ok and fixtures_ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
