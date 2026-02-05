import pyvisa

rm = pyvisa.ResourceManager()

for res_name in rm.list_resources():
    try:
        res = rm.open_resource(res_name)
        print(f"\nResource: {res_name}")
        print("  Interface type:", res.interface_type)
        print("  Resource class:", res.resource_class)
        print("  Timeout:", res.timeout)

        # Try standard identification
        try:
            print("  *IDN?:", res.query("*IDN?").strip())
        except Exception:
            print("  *IDN?: not supported")

        res.close()
    except Exception as e:
        print(f"\nResource: {res_name}")
        print("  Error opening resource:", e)
