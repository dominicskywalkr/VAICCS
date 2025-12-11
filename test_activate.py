from licensing.models import *
from licensing.methods import Key, Helpers

RSAPubKey = "<RSAKeyValue><Modulus>p4lCPtULuGY3wT8qtyDhmxV3WsLZ+nyZQuDGIDb+8ksyBjPNfbrqwjauyek9WlwSLAMqBa5khwLpBVwJVxIVz5af6RyxowZXOAjU8h0bhClCGsaqhraijoa2wVnSgSMz3/JcUIJgTMF9vwgTx0zHjBGyOOwHBvAgZyG6iQP29HUcWz2+fOPRNnaOF58U7QHgSsKVJB3XXaRmCIU9nmT3fCXYl+wSPje3LzKUE0XxnXLZA4yEunBygOs2CaNzN7S1LFJFiCfDhoPae5ql0ZvN2gQVLkdTxggowNahAsThDENTV82B1CPdhTIfJ8l5U1/tifQiq0OAXPZYiw+Li4K+lQ==</Modulus><Exponent>AQAB</Exponent></RSAKeyValue>"
auth = "WyIxMTUxNzY2MjgiLCJCWU9kVWpuVE13NEtpczl0UzRTeXZMa1F0Q0Q0dysrVzNob1lwMG1oIl0="

# Diagnostics: print machine code and capture full result / exceptions
mc = None
try:
    mc = Helpers.GetMachineCode(v=2)
    print("Machine code:", mc)
except Exception as e:
    print("Could not obtain machine code:", repr(e))

result = None
try:
    result = Key.activate(token=auth,
                          rsa_pub_key=RSAPubKey,
                          product_id=31607,
                          key="EWCCE-OQWVI-JXXMJ-ZHUIZ",
                          machine_code=mc)
    print("Raw result:", repr(result))
except Exception as exc:
    import traceback
    print("Exception calling Key.activate:", repr(exc))
    traceback.print_exc()

if not result or result[0] == None or not Helpers.IsOnRightMachine(result[0], v=2):
    # an error occurred or the key is invalid or it cannot be activated
    # (eg. the limit of activated devices was achieved)
    msg = None
    try:
        # result may be a tuple like (None, message)
        msg = result[1] if result and len(result) > 1 else None
    except Exception:
        msg = None
    print("The license does not work:", repr(msg))

    # Extra diagnostics: license object was returned but machine check failed.
    try:
        if result and result[0] is not None:
            lk = result[0]
            try:
                print("LicenseKey type:", type(lk))
                # show common attributes
                attrs = [a for a in dir(lk) if not a.startswith('_')]
                print("LicenseKey attrs:", attrs)
            except Exception as e:
                print("Could not list attributes:", repr(e))

            try:
                print("activated_machines:", getattr(lk, 'activated_machines', None))
            except Exception as e:
                print("Could not read activated_machines:", repr(e))

            try:
                print("f1..f8:", tuple(getattr(lk, f'f{i}', None) for i in range(1,9)))
            except Exception:
                pass

            try:
                print("expires:", getattr(lk, 'expires', None))
            except Exception:
                pass

            try:
                s = None
                try:
                    s = lk.save_as_string()
                except Exception:
                    # alternate name in some versions
                    if hasattr(lk, 'save_as_string'):
                        s = lk.save_as_string()
                print("save_as_string (first 200 chars):", repr(s)[:200])
            except Exception:
                pass
    except Exception as e:
        print("Error introspecting license object:", repr(e))
else:
    # everything went fine if we are here!
    print("The license is valid!")
    license_key = result[0]
    print("Feature 2: " + str(license_key.f2))
    print("License expires: " + str(license_key.expires))