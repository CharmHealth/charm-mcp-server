# Import tools from each module
from .core_tools import (
    core_tools_mcp,
    findPatients,
    getPracticeInfo
)

from .patient_management import (
    patient_management_mcp,
    managePatient,
    reviewPatientHistory
)

from .scheduling_tools import (
    scheduling_tools_mcp,
    manageAppointments
)

from .encounter_management import (
    encounter_management_mcp,
    manageEncounter
)

from .clinical_data import (
    clinical_data_mcp,
    managePatientVitals,
    managePatientDrugs,
    managePatientAllergies,
    managePatientDiagnoses
)

from .clinical_support import (
    clinical_support_mcp,
    managePatientNotes,
    managePatientRecalls,
    managePatientFiles,
    managePatientLabs
)

__all__ = [
    "core_tools_mcp",
    "patient_management_mcp",
    "scheduling_tools_mcp",
    "encounter_management_mcp",
    "clinical_data_mcp",
    "clinical_support_mcp",
    "findPatients",
    "getPracticeInfo",
    "managePatient", 
    "reviewPatientHistory",
    "manageAppointments",
    "manageEncounter",
    "managePatientVitals",
    "managePatientDrugs",
    "managePatientAllergies",        
    "managePatientDiagnoses",        
    "managePatientNotes",     
    "managePatientRecalls",          
    "managePatientFiles",
    "managePatientLabs"
]