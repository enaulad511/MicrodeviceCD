
import cadquery as cq

# Parámetros comunes
modulo = 1
altura = 10  # mm
agujero = 6.3  # 6 mm + 0.3 mm de holgura

def crear_engranaje(num_dientes, nombre_archivo):
    # Crear engranaje involuta
    gear = cq.Workplane("XY").gear(num_dientes, modulo, altura)
    
    # Crear agujero central
    gear = gear.faces("<Z").workplane().hole(agujero)
    
    # Exportar STL
    cq.exporters.export(gear, nombre_archivo)

# Crear engranajes
crear_engranaje(20, "engranaje_20.stl")
crear_engranaje(50, "engranaje_50.stl")

print("Archivos STL generados: engranaje_20.stl y engranaje_50.stl")
