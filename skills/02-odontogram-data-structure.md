# 🦷 Skill 02: Odontogram Data Structure

## Notación FDI (Fédération Dentaire Internationale)

```
SUPERIOR:     Derecha [18-11] | Izquierda [21-28]
INFERIOR:     Derecha [48-41] | Izquierda [31-38]
```

### Cuadrantes
- **1** (Superior Derecho): 11-18
- **2** (Superior Izquierdo): 21-28
- **3** (Inferior Izquierdo): 31-38
- **4** (Inferior Derecho): 41-48

### Dientes Temporarios (Niños)
- **5** (Sup. Der.): 51-55
- **6** (Sup. Izq.): 61-65
- **7** (Inf. Izq.): 71-75
- **8** (Inf. Der.): 81-85

## Caras del Diente
| Cara | Descripción |
|------|-------------|
| Oclusal | Cara de masticación (superior) |
| Vestibular | Cara hacia el labio/mejilla |
| Palatina/Lingual | Cara hacia el paladar/lengua |
| Mesial | Cara hacia la línea media |
| Distal | Cara opuesta a la línea media |

## Simbología
| Símbolo | Significado |
|---------|------------|
| Relleno coloreado | Restauración en esa cara |
| **X** | Extracción o diente extraído |
| **O** | Caries |
| ⌓ | Corona |
| ▭ | Prótesis fija |
| ▯ | Prótesis removible |
| ↓ | Tratamiento de conducto |
| ⊥ | Implante |

## Colores
- 🔴 **ROJO** = Preexistente (hallazgo que ya estaba al momento del examen)
- 🔵 **AZUL** = Prestación nueva (trabajo realizado o a realizar)

## Campos del Registro
- Diente Nº (FDI)
- Cara
- Código de prestación
- Conformidad del paciente
- Matrícula del profesional
- Cantidad
- Reservado Obra Social
