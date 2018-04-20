#!/usr/bin/env python3

from dispatch import dispatch

def main():
    suite_result = dispatch("/path/to/file", "clc_chaTT", [])
    print("suite_result={:s}".format(repr(suite_result)))

if __name__ == "__main__":
    main()
