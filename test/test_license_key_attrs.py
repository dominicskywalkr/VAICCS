from licensing.models import LicenseKey
import inspect

sig = inspect.signature(LicenseKey.__init__)
params = list(sig.parameters.keys())
print("LicenseKey.__init__ parameters:")
for p in params:
    print(f"  - {p}")
    if 'customer' in p.lower() or 'email' in p.lower():
        print(f"    ^^^ FOUND CUSTOMER/EMAIL FIELD")
