# Looking inside the box
*TL;DR This blog post talks about reverse engineering the Dropbox client, breaking its obfuscation mechanisms, de-compiling it to Python code as well as modifying the client in order to use debug features which are normally hidden from view. If you're just interested in relevant code and notes please scroll to the end. As of this writing it is up to date with the current versions of Dropbox which are based on the CPython 3.6 interpreter.*


## Introduction

As tempting as it would be to turn a blog post with this title into a postmodern critical analysis of the movie *Se7en* I’ll be discussing another kind of box today. Dropbox to be exact. I have been fascinated by Dropbox from the moment it came on my radar shortly after launching. Dropbox’ concept is still deceptively simple. Here’s a folder. Put files in it. Now it syncs. Move to another computing device. It syncs. The folder and files are there now too!

The amount of work that goes on behind the scenes of such an application is staggering though. First there are all the issues the engineers need to deal with when building and maintaining a cross-platform application for the major desktop operating systems (OS X, Linux, Windows). Add to that all the support for different web browsers, different mobile operating systems. And that’s just talking about the local client. The back-end of Dropbox’ infrastructure which enabled them to achieve scalability, low-latency with insanely write-heavy workloads whilst supporting half a billion users is just as interesting to me.

It’s for those reasons I always liked seeing what Dropbox did under the hood and how it evolved over the years. My first attempts at figuring out how the Dropbox client actually worked were roughly eight years ago after I saw some unknown broadcast traffic on a hotel network. Upon investigating it turned out to have been a part of Dropbox’ feature called *LanSync* which enables faster synchronization if Dropbox nodes on the same local network have access to the same files. However, the protocol was not documented and I wanted to know more. So I decided to look at the client in more detail. I ended up reverse engineering a lot of the client. This research was never published although I did share some notes here and there with some folks.

When starting Anvil Ventures, Chris and I, evaluated a number of tools for document storage, sharing and collaboration. One of these was obviously Dropbox and that was another reason for me to dig up my old research notes and check it against the current status of the Dropbox client.


## Decryption and Unobfuscation

At the time I downloaded the Dropbox client for Linux. I was quick to find by running strings over it  that the Dropbox client was written in Python. As the Python license is fairly permissive it’s easy for people to modify and distribute a Python interpreter together with other dependencies as commercial software. I then embarked on a reverse engineering project to see if I could figure out how the client worked. 

At the time the byte-compiled files were in a ZIP file that was concatenated to the Linux *dropbox* binary itself. The main binary was simply a modified Python interpreter that would then load itself by hijacking the Python import mechanisms. Every subsequent import call would then be redirected by parsing the ZIP file inside the binary. Of course extracting the ZIP file from this binary was easy by simply running unzip on it. Besides that a tool like [binwalk](https://github.com/ReFirmLabs/binwalk) would have done the job to extract the file with all the byte-compiled *pyc-files* in it.

As I couldn't break the encryption applied to the byte-compiled *pyc*-files at the time, I ended up taking a Python standard library shared object that I recompiled with a *"backdoor"* in it. When Dropbox now ran and loaded this *.so file* I could use this to easily execute arbitrary Python code in the running interpreter. Although I discovered this independently the same technique was used by *Florian Ledoux* and *Nicolas Ruff* in a [presentation](http://archive.hack.lu/2012/Dropbox%20security.pdf) given at *Hack.lu* in 2012.

Being able to investigate and manipulate the running Dropbox Python code lead me down the rabbit-hole. Several anti-debugging tricks were used to make it harder to dump the [code objects](https://docs.python.org/3.6/library/functions.html#compile). For example under normal CPython interpreter conditions it's easy to get the compiled bytecode representing a function back. A quick example:


    >>> def f(i=0):
    ...     return i * i
    ...
    >>> f.__code__
    <code object f at 0x109deb540, file "<stdin>", line 1>
    >>> f.__code__.co_code
    b'|\x00|\x00\x14\x00S\x00'
    >>> import dis
    >>> dis.dis(f)
      2           0 LOAD_FAST                0 (i)
                  2 LOAD_FAST                0 (i)
                  4 BINARY_MULTIPLY
                  6 RETURN_VALUE
    >>>

But the `co_code` property was patched out of the exposed member list in the compiled version of `Objects/codeobject.c`. This member list normally looks something like the following and by simply removing the `co_code` property one cannot dump those code objects anymore.


    static PyMemberDef code_memberlist[] = {
    ...
        {"co_flags",        T_INT,          OFF(co_flags),          READONLY},
        {"co_code",         T_OBJECT,       OFF(co_code),           READONLY},
        {"co_consts",       T_OBJECT,       OFF(co_consts),         READONLY},
    ...
    };

Besides that other libraries such as the standard Python [disassembler](https://docs.python.org/3.6/library/dis.html) were removed. In the end I managed to dump the code objects to files but I still couldn't decompile them. It took me a while to figure out what was going on until I realized that the `opcodes` as used by the Dropbox interpreter were not the same as the standard Python opcodes. So the problem then becomes how to figure out what the new opcodes are so one can rewrite the code objects back to the original Python byte code.

One option for this is called `opcode remapping` and it was, to the best of my knowledge, pioneered by Rich Smith and presented at [Defcon 18](https://www.youtube.com/watch?v=tYHsv7Mzv5g). In this talk he also introduced [pyREtic](https://github.com/MyNameIsMeerkat/pyREtic) which was an approach to in-memory reverse engineering of Python bytecode. The *pyREtic* code seems fairly unmaintained and targeted towards *"old"* Python 2.x binaries. Rich's talk is highly recommended.

The opcode remapping technique takes all the code objects of the Python standard library and compares them to the one extracted from the Dropbox binary. For example, the code-objects in `hashlib.pyc` or `socket.pyc` which are in the standard library. If each time, for example, opcode `0x43` matches unobfuscated opcode `0x21` one can slowly build up a translation table to rewrite code objects. Then those code objects can be put through a Python decompiler. It still requires patching the modified interpreter to even be able to dump the code objects by making sure that the `co_code` object is exposed properly.

Another option is to break the serialization format. In Python this is called [marshalling](https://docs.python.org/3.6/library/marshal.html). Simply trying to load the obfuscated files by unmarshalling them the usual route did not work. Upon reverse engineering the binary using IDA Pro I discovered that there's a specific decryption phase taking place. The first person that seemed to have published something on this publicly was Hagen Fristsch in this [blogpost](https://itooktheredpill.irgendwo.org/2012/dropbox-decrypt/). In it he alludes to changes being made in newer versions of Dropbox  (when Dropbox switched from using Python 2.5 to Python 2.7 for its builds). The algorithm works as follows:


- When unmarshalling a *pyc* file the header is being read to determine the marshalling version. This format is explicitly undocumented save for the CPython implementation itself.
- The format defines a list of types which are encoded in it. Types are *True, False*, *floats* etc but the most important one is the type for the aforementioned Python *code* object.
- When loading a *code object* two extra values first are being read from the input file.
    - The first is a 32 bit sized *random* value
    - The second is a 32 bit sized *length* value denoting the length of the serialized code object.
- Both the *rand* and *length* value are then fed into a simple “RNG” function yielding a *seed.*
- This *seed* value is then supplied to a [*Mersenne Twister*](https://en.wikipedia.org/wiki/Mersenne_Twister) and four 32-bit values are being generated.
- These four values concatenated together yield the encryption key for the serialized data. The encryption algorithm then is the [Tiny Encryption Algorithm](https://en.wikipedia.org/wiki/Tiny_Encryption_Algorithm) which is then used to decrypt the data.

In the code I ended up writing I wrote a Python based unmarshaller from scratch. The part that decrypts the code objects looks something like the excerpt below. It should be noted that this method will have to be called recursively too. The top-level object for a *pyc* file is a code-object which then contains code objects which can be classes, functions or lambdas, which can then themselves contain methods, functions or lambdas.  It’s code-objects all the way down!


    def load_code(self):
        rand = self.r_long()
        length = self.r_long()
    
        seed = rng(rand, length)
        mt = MT19937(seed)
        key = []
        for i in range(0, 4):
            key.append(mt.extract_number())
    
        # take care of padding for size calculation
        sz = (length + 15) & ~0xf
        words = sz / 4
    
        # convert data to list of dwords
        buf = self._read(sz)
        data = list(struct.unpack("<%dL" % words, buf))
    
        # decrypt and convert back to stream of bytes
        data = tea.tea_decipher(data, key)
        data = struct.pack("<%dL" % words, *data)
    
    

Being able to decrypt the code-objects means that after the patched unmarshalling routines we should now rewrite the actual byte code. The code objects contain information on line numbers, constants and other information. The actual byte code is in the `co_code` object. Assuming we have built up the opcode mapping we can simply replace the opcodes here from the obfuscated Dropbox values to the standard Python 3.6 equivalents.

After that is done the code objects are now in normal Python 3.6 format and they can be passed to a decompiler. The state of Python decompilers has tremendously improved with the [uncompyle6](https://github.com/rocky/python-uncompyle6/) by R. Bernstein. Using that yielded me pretty good results and I was able to put everything together in a tool that decompiles a current version of Dropbox to the best of its abilities.

If you clone this [repo](https://github.com/anvilventures/lookinsidethebox) and follow the instructions the ultimate output should be something like the below:


    ...
    __main__ - INFO - Successfully decompiled dropbox/client/features/browse_search/__init__.pyc
    __main__ - INFO - Decrypting, patching and decompiling _bootstrap_overrides.pyc
    __main__ - INFO - Successfully decompiled _bootstrap_overrides.pyc
    __main__ - INFO - Processed 3713 files (3591 succesfully decompiled, 122 failed)
    opcodemap - WARNING - NOT writing opcode map as force overwrite not set

 
This means one now has the directory named *out*/ containing a decompiled version of the Dropbox source code. 


## Enabling Dropbox tracing

When looking around trying to find something interesting in the decompiled code the following caught my eye. In `dropbox/client/high_trace.py` the trace handlers are only installed if the build is not frozen or a magic key or support cookie is set at line 1430.


    1424 def install_global_trace_handlers(flags=None, args=None):
    1425     global _tracing_initialized
    1426     if _tracing_initialized:
    1427         TRACE('!! Already enabled tracing system')
    1428         return
    1429     _tracing_initialized = True
    1430     if not build_number.is_frozen() or magic_trace_key_is_set() or limited_support_cookie_is_set():
    1431         if not os.getenv('DBNOLOCALTRACE'):
    1432             add_trace_handler(db_thread(LtraceThread)().trace)
    1433         if os.getenv('DBTRACEFILE'):
    1434             pass

The frozen part refers to internal Dropbox debug builds. Looking a bit above in the same file the following can be found:


    272 def is_valid_time_limited_cookie(cookie):
    273     try:
    274         try:
    275             t_when = int(cookie[:8], 16) ^ 1686035233
    276         except ValueError:
    277             return False
    278         else:
    279             if abs(time.time() - t_when) < SECONDS_PER_DAY * 2 and md5(make_bytes(cookie[:8]) + b'traceme').hexdigest()[:6] == cookie[8:]:
    280                 return True
    281     except Exception:
    282         report_exception()
    283
    284     return False
    285
    286
    287 def limited_support_cookie_is_set():
    288     dbdev = os.getenv('DBDEV')
    289     return dbdev is not None and is_valid_time_limited_cookie(dbdev)
    build_number/environment.py

As can be seen in the method `limited_support_cookie_is_set` at line 287, only if an environment variable named `DBDEV` is set  properly to a time limited cookie will the tracing be turned on. Well that’s interesting! And we now know how to generate such time limited cookies. It’s expected based on the name that Dropbox engineers can generate these cookies and then turn on tracing temporarily for specific customer support cases. After Dropbox restarts or the computer reboots, even if said cookie is still in the environment it will automatically expire. This, I speculate, is to prevent for example performance degradation due to continuous tracing. It also makes it harder for people to reverse engineer Dropbox if they can’t that easily figure out how to disable tracing!

A quick script however can just generate these cookies and set them properly. Something like this:


    #!/usr/bin/env python3
    def output_env(name, value):
        print("%s=%s; export %s" % (name, value, name))
    
    def generate_time_cookie():
        t = int(time.time())
        c = 1686035233
        s = "%.8x" % (t ^ c)
        h = md5(s.encode("utf-8?") + b"traceme").hexdigest()
        ret = "%s%s" % (s, h[:6])
        return ret
    c = generate_time_cookie()
    output_env("DBDEV", c)

This will then generate a time based cookie as such:


    $ python3 setenv.py
    DBDEV=38b28b3f349714; export DBDEV;

Then load  the output of that script properly into the environment and after that run the Dropbox client.


    $ eval `python3 setenv.py`
    $ ~/.dropbox-dist/dropbox-lnx_64-71.4.108/dropbox

This will actually turn on the tracing output which is colorized and everything. It will look somewhat like the below for an unregistered Dropbox client.

![tracing enabled in Dropbox](litb_tracing.png)

## Injecting new code 

So that’s mildly fun. Looking a bit further in the decompiled output there’s `out/build_number/environment.pyc`. There’s a function in there which checks if a specific magic key is set. This key is not hard coded in the source but it’s compared against a SHA-256 hash. See below for an excerpt.


      1 import hashlib, os
      2 from typing import Optional, Text
      3 _MAGIC_TRACE_KEY_IS_SET = None
      4
      5 def magic_trace_key_is_set():
      6     global _MAGIC_TRACE_KEY_IS_SET
      7     if _MAGIC_TRACE_KEY_IS_SET is None:
      8         dbdev = os.getenv('DBDEV') or ''
      9         if isinstance(dbdev, Text):
     10             bytes_dbdev = dbdev.encode('ascii')
     11         else:
     12             bytes_dbdev = dbdev
     13         dbdev_hash = hashlib.sha256(bytes_dbdev).hexdigest()
     14         _MAGIC_TRACE_KEY_IS_SET = dbdev_hash == 'e27eae61e774b19f4053361e523c771a92e838026da42c60e6b097d9cb2bc825'
     15     return _MAGIC_TRACE_KEY_IS_SET

A lot of different code calls into this method to see whether the magic trace key is set. I tried cracking the SHA-256 hash for a bit using [John the Ripper](https://www.openwall.com/john/), but it took too long and I have no good indication what the contents would be to be a bit more intelligent about cracking it. At the end of the day internally in Dropbox the organizations the developers have a specific hard-coded development key which they can set in their environment. The moment they do so they can switch a client into a mode where the magic tracing key is set.

This annoyed me however as I just wanted to have a quick and easy way to run dropbox with this tracing key set. So I wrote a marshalling routine that enabled me to generate encrypted pyc files as per the Dropbox encryption. This way I was able to inject my own code or to simply replace the hash above. This code can be found in the Github repository too under `patchzip.py`. I ended up replacing the hash with the SHA-256 hash of `ANVILVENTURES`. Then the code object would be re-encrypted again and put in the zipfile containing all the obfuscated code. This now enabled me to do the following:


    $ DBDEV=ANVILVENTURES; export DBDEV;
    $ ~/.dropbox-dist/dropbox-lnx_64-71.4.108/dropbox

This resulted in all these debug features showing up when right-clicking the Dropbox icon in the system tray.

![Debug options enabled in Dropbox](litb_debugging.png)


When looking a bit further in the decompiled source code in the file `dropbox/webdebugger/server.py` I found that there’s a method named `is_enabled` which seems to be checked to see whether an embedded web debugger should be enabled. First of all it checks if the previously mentioned magic key is set. As we replaced that SHA-256 hash we can simply set it to `ANVILVENTURES`. The second part at line 201 and 202 checks whether there’s an environment variable with the name `DB<x>` with x being equal to the SHA-256 hash. The value of the environment should be a time limited cookie as we’ve seen earlier.


    191     @classmethod
    192     def is_enabled(cls):
    193         if cls._magic_key_set:
    194             return cls._magic_key_set
    195         else:
    196             cls._magic_key_set = False
    197             if not magic_trace_key_is_set():
    198                 return False
    199             for var in os.environ:
    200                 if var.startswith('DB'):
    201                     var_hash = hashlib.sha256(make_bytes(var[2:])).hexdigest()
    202                     if var_hash == '5df50a9c69f00ac71f873d02ff14f3b86e39600312c0b603cbb76b8b8a433d3ff0757214287b25fb01' and is_valid_time_limited_cookie(os.environ[var]):
    203                         cls._magic_key_set = True
    204                         return True
    205
    206             return False

Using exactly the same technique by replacing this hash with the SHA-256 hash used before we can now change the previously written `setenv`  script to something like this at the bottom:


    $ cat setenv.py
    …
    c = generate_time_cookie()
    output_env("DBDEV", "ANVILVENTURES")
    output_env("DBANVILVENTURES", c)
    $ python3 setenv.py


    DBDEV=ANVILVENTURES; export DBDEV;
    DBANVILVENTURES=38b285c4034a67; export DBANVILVENTURES
    $ eval `python3 setenv.py`
    $ ~/.dropbox-dist/dropbox-lnx_64-71.4.108/dropbox

As can be seen after the client has started a new listening TCP port has been opened. One that wasn’t open when the environment variables weren’t set properly.


    $ netstat --tcp -lnp | grep dropbox
    tcp        0      0 127.0.0.1:4242              0.0.0.0:*               LISTEN      1517/drpobox              

Looking further in the code it can be seen in the `webpdb.pyc` that there’s a WebSocket interface that wraps the standard Python [pdb](https://docs.python.org/3.6/library/pdb.html) utilities and that is exposed via the HTTP server running behind this port. Let’s install a [websocket client](https://github.com/vi/websocat/) and give it a go:


    $ websocat -t ws://127.0.0.1:4242/pdb
    --Return--
    
    > /home/gvb/dropbox/webdebugger/webpdb.pyc(101)run()->None
    >
    (Pdb) from build_number.environment import magic_trace_key_is_set as ms
    (Pdb) ms()
    True


## Conclusion 

We managed to successfully reverse engineer Dropbox, write decryption and injection tools for it that work with current Dropbox clients based on Python 3.6 releases and successfully reverse engineer features and enable them. Obviously now that the debugger can be enabled this will really help reverse engineering the application further. Especially with the subset of files that could not be successfully decompiled due to the decompyle6 decompiler simply not being perfect. 

For more information don’t hesitate to contact me directly at [gvb@anvilventures.com](mailto:gvb@anvilventures.com).


## Code

The code can be found at [Github](https://github.com/anvilventures/lookinsidethebox). Instructions on how to use it are included there too. That repository also contains my historical code which was written in 2011. This code should work with just a few modifications provided someone has older Dropbox releases laying around.
used to be based on Python 2.7. Scripts to generate the opcode mapping as well as how to set the Dropbox environment variables as well as the *zip patching* file are included.

## Acknowledgements

Thanks to Anvil Ventures' Brian Bauer for reviewing my code. This code and work has been shaped over the course of several years of me revisiting it every once in a while and updating it to newer/other techniques and rewriting things to make it work again with Dropbox' newer versions. 

As mentioned in this post the publicly available work done by folks like Rich Smith, Florian Ledoux and Nicolas Ruff as well as Hagen Fritsch, should serve a great starting point to learn more about reverse engineering Python based applications especially one of the biggest of all of them; the Dropbox client.

Of note should be that the current state of Python decompilation has been pushed a great deal forward by R. Bernstein consolidating and improving the myriad of different Python decompilers in [uncompyle6](https://github.com/rocky/python-uncompyle6).

Also many thanks to Anvilians Brian, Austin, Stefan and Chris for reviewing this blogpost.






