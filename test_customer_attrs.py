from licensing.models import LicenseKey

# Try to create a minimal LicenseKey and access Customer
# We can check the structure without fully instantiating
try:
    import licensing.models as models
    
    # Look at the LicenseKey source
    import inspect
    source_file = inspect.getsourcefile(models.LicenseKey)
    print(f"Source: {source_file}")
    
    # Try to find Customer class
    if hasattr(models, 'Customer'):
        print("Found Customer class in models")
        sig = inspect.signature(models.Customer.__init__)
        print("Customer.__init__ params:", list(sig.parameters.keys()))
    else:
        print("No Customer class found in models")
        print("Available in models:", [x for x in dir(models) if 'customer' in x.lower() or 'email' in x.lower()])
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
