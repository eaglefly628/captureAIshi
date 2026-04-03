# C/C++ Code Rules

- **ASCII only in source files.** No Unicode characters (arrows, em-dashes, special symbols) in `.cpp`/`.h` files. The MSVC build uses `/W4 /WX` (warnings as errors) and code page 936 triggers C4819 for non-ASCII. Use `->` not `→`, `~` not `≈`, `--` not `—`.
- All strings and comments must be plain ASCII.
