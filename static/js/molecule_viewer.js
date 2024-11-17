const stage = new NGL.Stage("viewport");

// Color scheme for elements (using atomic numbers)
const elementColors = {
    1: [1, 1, 1],     // H: White
    6: [0.5, 0.5, 0.5], // C: Grey
    7: [0, 0, 1],     // N: Blue
    8: [1, 0, 0],     // O: Red
    15: [1, 0.5, 0],  // P: Orange
    16: [1, 1, 0],    // S: Yellow
    'default': [0, 1, 0]   // Green (for other elements)
};

let pickedAtoms = [];
let distancePairs = [];
let currentAtomData = [];
let isInitialLoad = true;
let isAddingPairInNGL = false;
let tempPairAtoms = [];

function getElementColor(atomicNumber) {
    return elementColors[atomicNumber] || elementColors['default'];
}

function getElementSymbol(atomicNumber) {
    const symbols = {
        1: 'H', 6: 'C', 7: 'N', 8: 'O', 15: 'P', 16: 'S'
    };
    return symbols[atomicNumber] || `Element${atomicNumber}`;
}

function loadMolecule(pdb_id) {
    console.log('Loading molecule:', pdb_id);
    // Clear existing components and picks
    stage.removeAllComponents();
    pickedAtoms = [];
    currentAtomData = [];
    updateAtomList();
    distancePairs = [];
    updatePairList();

    fetch(`/get_molecule/${pdb_id}`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(atomData => {
            console.log('Atom data received:', atomData.slice(0, 5));
            if (!atomData || atomData.length === 0) {
                throw new Error('Received empty atom data');
            }
            
            currentAtomData = atomData;
            
            // Create a shape component for the atoms
            const shape = new NGL.Shape('atom_points');
            atomData.forEach((atom, index) => {
                const color = getElementColor(atom.element);
                shape.addSphere([atom.x, atom.y, atom.z], color, 0.5, `atom${index}`);
            });
            
            // Add the shape component to the stage
            const shapeComp = stage.addComponentFromObject(shape);
            shapeComp.addRepresentation('point');
            
            // Only set the view once when the molecule is initially loaded
            if (isInitialLoad) {
                stage.autoView();
                isInitialLoad = false;
            }
            
            console.log('Molecule loaded successfully');

            // Add picking functionality
            stage.mouseControls.add("clickPick-left", function(stage, pickingProxy) {
                if (pickingProxy && pickingProxy.object && pickingProxy.object.name) {
                    const atomIndex = parseInt(pickingProxy.object.name.slice(4));  // Extract index from "atomX" name
                    if (!isNaN(atomIndex) && atomIndex < atomData.length) {
                        const atom = atomData[atomIndex];
                        if (isAddingPairInNGL) {
                            handlePairSelection(atom, atomIndex);
                        } else {
                            toggleAtomSelection(atom, atomIndex);
                        }
                    }
                }
            });

            // Load state from URL if available
            loadStateFromURL();
        })
        .catch(error => {
            console.error('Error loading molecule:', error);
        });
}

function updateAtomList() {
    const atomListBody = document.querySelector('#atomList tbody');
    const atom1Select = document.getElementById('atom1Select');
    const atom2Select = document.getElementById('atom2Select');
    
    atomListBody.innerHTML = '';
    atom1Select.innerHTML = '<option value="">Select Atom 1</option>';
    atom2Select.innerHTML = '<option value="">Select Atom 2</option>';
    
    pickedAtoms.forEach((atom, index) => {
        const tr = document.createElement('tr');
        tr.dataset.atomIndex = index;
        tr.innerHTML = `
            <td>${index + 1}</td>
            <td>${atom.id}</td>
            <td>${getElementSymbol(atom.element)}</td>
            <td>(${atom.x.toFixed(2)}, ${atom.y.toFixed(2)}, ${atom.z.toFixed(2)})</td>
            <td>
                <button class="button button-outline btn-small center-btn">Center</button>
                <button class="button button-outline btn-small delete-btn">Delete</button>
            </td>
        `;
        atomListBody.appendChild(tr);

        tr.querySelector('.center-btn').onclick = () => centerOnAtom(atom);
        tr.querySelector('.delete-btn').onclick = () => deleteAtom(index);

        const option = document.createElement('option');
        option.value = index;
        option.textContent = `Match ${index + 1}: ${getElementSymbol(atom.element)} (DB ID: ${atom.id})`;
        atom1Select.appendChild(option.cloneNode(true));
        atom2Select.appendChild(option);
    });
}

function updatePairList() {
    const pairListBody = document.querySelector('#pairList tbody');
    pairListBody.innerHTML = '';
    
    distancePairs.forEach((pair, index) => {
        const atom1MatchNumber = pickedAtoms.findIndex(a => a.id === pair.atom1.id) + 1;
        const atom2MatchNumber = pickedAtoms.findIndex(a => a.id === pair.atom2.id) + 1;

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${index + 1}</td>
            <td>${getElementSymbol(pair.atom1.element)} (Match#: ${atom1MatchNumber}, DB ID: ${pair.atom1.id})</td>
            <td>${getElementSymbol(pair.atom2.element)} (Match#: ${atom2MatchNumber}, DB ID: ${pair.atom2.id})</td>
            <td>${pair.distance.toFixed(2)} Å</td>
            <td>
                <button class="button button-outline btn-small center-btn">Center</button>
                <button class="button button-outline btn-small delete-btn">Delete</button>
            </td>
        `;
        pairListBody.appendChild(tr);

        tr.querySelector('.center-btn').onclick = () => centerOnPair(pair);
        tr.querySelector('.delete-btn').onclick = () => deletePair(index);

        // Add hover effect
        tr.addEventListener('mouseenter', () => {
            highlightAtoms(atom1MatchNumber - 1, atom2MatchNumber - 1);
        });
        tr.addEventListener('mouseleave', () => {
            unhighlightAtoms();
        });
    });
}

function highlightAtoms(index1, index2) {
    const atomRows = document.querySelectorAll('#atomList tbody tr');
    atomRows.forEach((row, index) => {
        if (index === index1 || index === index2) {
            row.style.backgroundColor = 'yellow';
        }
    });
}

function unhighlightAtoms() {
    const atomRows = document.querySelectorAll('#atomList tbody tr');
    atomRows.forEach(row => {
        row.style.backgroundColor = '';
    });
}

function loadStateFromURL() {
    const hash = window.location.hash.slice(1);
    if (hash) {
        try {
            const state = JSON.parse(decodeURIComponent(hash));
            document.getElementById('pdbSelect').value = state.pdbId;
            pickedAtoms = state.pickedAtoms;
            distancePairs = state.distancePairs;
            updateAtomList();
            updateAtomHighlights();
            updatePairList();
            drawDistancePairs();
        } catch (error) {
            console.error('Error loading state from URL:', error);
        }
    }
}

function updateURL() {
    const state = {
        pdbId: document.getElementById('pdbSelect').value,
        pickedAtoms: pickedAtoms,
        distancePairs: distancePairs
    };
    const stateString = encodeURIComponent(JSON.stringify(state));
    window.location.hash = stateString;
}

// Fetch available PDB identifiers
function fetchPDBIdentifiers(searchTerm = '') {
    fetch(`/get_pdb_identifiers?search=${encodeURIComponent(searchTerm)}`)
        .then(response => response.json())
        .then(data => {
            const pdbSelect = document.getElementById('pdbSelect');
            pdbSelect.innerHTML = ''; // Clear existing options
            if (data.error) {
                console.error('Error fetching PDB identifiers:', data.error);
                return;
            }
            data.forEach(pdb => {
                const option = document.createElement('option');
                option.value = pdb.id;
                option.text = pdb.id;
                pdbSelect.add(option);
            });
            // Load the first molecule by default if it's the initial load
            if (data.length > 0 && isInitialLoad) {
                console.log('Loading first molecule:', data[0].id);
                loadMolecule(data[0].id);
                isInitialLoad = false;
            }
        })
        .catch(error => {
            console.error('Error fetching PDB identifiers:', error);
        });
}

// Create and add the search input to the DOM
function createSearchInput() {
    const searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.id = 'pdbSearch';
    searchInput.placeholder = 'Search PDB...';

    const pdbSelectContainer = document.getElementById('pdbSelect').parentNode;
    pdbSelectContainer.insertBefore(searchInput, document.getElementById('pdbSelect'));

    // Add event listener for search input
    searchInput.addEventListener('input', function() {
        fetchPDBIdentifiers(this.value);
    });
}

// Call this function to create the search input when the page loads
createSearchInput();

// Initial fetch of PDB identifiers (first 25)
fetchPDBIdentifiers();

// Modify the existing event listener for pdbSelect
document.getElementById('pdbSelect').addEventListener('change', function() {
    const pdb_id = this.value;
    console.log('Selection changed, loading molecule:', pdb_id);
    loadMolecule(pdb_id);
});

// Implement search functionality
// searchDatabase
document.getElementById('searchButton').addEventListener('click', function() {

    if (distancePairs.length === 0) {
        alert('Please add at least one distance pair before searching.');
        return;
    }
    const searchData = distancePairs.map(pair => ({
        atom1: {
            element: pair.atom1.element,
            origin: pair.atom1.origin,
            matchid: pickedAtoms.findIndex(a => a.id === pair.atom1.id) + 1
        },
        atom2: {
            element: pair.atom2.element,
            origin: pair.atom2.origin,
            matchid: pickedAtoms.findIndex(a => a.id === pair.atom2.id) + 1
        },
        distance: pair.distance
    }));

    // Open a new tab with the search results template
    const newTab = window.open(`/search_results?usePostGIS=${document.getElementById('usePostGIS').checked}`, '_blank');

    // Wait for the new tab to load
    newTab.addEventListener('load', function() {
        // First, get the SQL query
        fetch('/search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                selected_pairs: searchData,
                use_postgis: document.getElementById('usePostGIS').checked,
                skip_execution: true
            })
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => { throw err; });
            }
            return response.json();
        })
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            } else if (data.sql_query) {
                // Initialize the search results in the new tab
                newTab.initializeSearchResults(data.sql_query, searchData);
            } else {
                throw new Error('Unexpected response from server');
            }
        })
        .catch(error => {
            console.error('Error during search:', error);
            newTab.document.getElementById('errorMessage').textContent = `An error occurred: ${error.message}. Please try again.`;
        });
    });
});

// Load initial state from URL
window.addEventListener('load', loadStateFromURL);

function updateAtomHighlights() {
    let shapeComp = stage.getComponentsByName('atom_points')[0];
    const shape = new NGL.Shape('atom_points');
    
    currentAtomData.forEach((atom, index) => {
        const color = getElementColor(atom.element);
        const isSelected = pickedAtoms.some(a => a.index === index);
        const radius = isSelected ? 0.75 : 0.5;  // Increase size for selected atoms
        const adjustedColor = isSelected ? color.map(c => Math.min(c * 1.2, 1)) : color;  // Make selected atoms brighter
        shape.addSphere([atom.x, atom.y, atom.z], adjustedColor, radius, `atom${index}`);
    });

    if (shapeComp) {
        shapeComp.setShape(shape);
        shapeComp.removeAllRepresentations();
    } else {
        shapeComp = stage.addComponentFromObject(shape);
    }
    
    shapeComp.addRepresentation('point');
    stage.viewer.requestRender();
}

function drawDistancePairs() {
    // Remove existing distance-pairs component
    let pairComp = stage.getComponentsByName('distance-pairs')[0];
    if (pairComp) {
        stage.removeComponent(pairComp);
    }

    // Only create new component if there are pairs to draw
    if (distancePairs.length > 0) {
        const shape = new NGL.Shape('distance-pairs');
        distancePairs.forEach((pair, index) => {
            shape.addCylinder(
                [pair.atom1.x, pair.atom1.y, pair.atom1.z],
                [pair.atom2.x, pair.atom2.y, pair.atom2.z],
                [1, 1, 0],  // yellow color
                0.1  // radius
            );
        });
        pairComp = stage.addComponentFromObject(shape);
        pairComp.addRepresentation('buffer');
    }
    stage.viewer.requestRender();
}

function centerOnAtom(atom) {
    const position = new NGL.Vector3(atom.x, atom.y, atom.z);
    stage.animationControls.zoomMove(
        position,
        position.distanceTo(stage.viewer.camera.position) / 4,  // zoom level
        1000  // duration in milliseconds
    ).then(() => {
        // Prevent auto zoom-out
        //stage.animationControls.move(position, 0);
    });
}

function centerOnPair(pair) {
    const center = new NGL.Vector3(
        (pair.atom1.x + pair.atom2.x) / 2,
        (pair.atom1.y + pair.atom2.y) / 2,
        (pair.atom1.z + pair.atom2.z) / 2
    );
    const distance = Math.sqrt(
        Math.pow(pair.atom1.x - pair.atom2.x, 2) +
        Math.pow(pair.atom1.y - pair.atom2.y, 2) +
        Math.pow(pair.atom1.z - pair.atom2.z, 2)
    );
    stage.animationControls.zoomMove(
        center,
        distance * 5,  // zoom level
        1000  // duration in milliseconds
    ).then(() => {
        // Prevent auto zoom-out
        //stage.animationControls.move(center, 0);
    });
}

function deleteAtom(index) {
    const deletedAtom = pickedAtoms[index];
    pickedAtoms.splice(index, 1);
    
    // Remove all pairs that include the deleted atom
    distancePairs = distancePairs.filter(pair => 
        pair.atom1.index !== deletedAtom.index && pair.atom2.index !== deletedAtom.index
    );

    updateAtomList();
    updatePairList();
    updateURL();

    // Update the NGL viewer
    updateNGLViewer();
}

function deletePair(index) {
    distancePairs.splice(index, 1);
    updatePairList();
    updateURL();

    // Update the NGL viewer
    updateNGLViewer();
}

function updateNGLViewer() {
    // Remove all existing components
    stage.removeAllComponents();

    // Recreate the atom points
    const shape = new NGL.Shape('atom_points');
    currentAtomData.forEach((atom, index) => {
        const isSelected = pickedAtoms.some(a => a.index === index);
        const color = getElementColor(atom.element);
        const radius = isSelected ? 0.75 : 0.5;
        const adjustedColor = isSelected ? color.map(c => Math.min(c * 1.2, 1)) : color;
        shape.addSphere([atom.x, atom.y, atom.z], adjustedColor, radius, `atom${index}`);
    });

    const shapeComp = stage.addComponentFromObject(shape);
    shapeComp.addRepresentation('point');

    // Recreate the distance pairs
    if (distancePairs.length > 0) {
        const pairShape = new NGL.Shape('distance-pairs');
        distancePairs.forEach((pair, index) => {
            pairShape.addCylinder(
                [pair.atom1.x, pair.atom1.y, pair.atom1.z],
                [pair.atom2.x, pair.atom2.y, pair.atom2.z],
                [1, 1, 0],  // yellow color
                0.1  // radius
            );
        });
        const pairComp = stage.addComponentFromObject(pairShape);
        pairComp.addRepresentation('buffer');
    }

    stage.viewer.requestRender();
}

function toggleAtomSelection(atom, index) {
    const existingIndex = pickedAtoms.findIndex(a => a.index === index);
    if (existingIndex !== -1) {
        pickedAtoms.splice(existingIndex, 1);
        // Remove all pairs that include this atom
        distancePairs = distancePairs.filter(pair => 
            pair.atom1.index !== index && pair.atom2.index !== index
        );
    } else {
        pickedAtoms.push({...atom, index});
    }
    updateAtomList();
    updatePairList();
    updateURL();

    // Update the NGL viewer
    updateNGLViewer();
}

function handlePairSelection(atom, index) {
    tempPairAtoms.push({...atom, index});
    if (tempPairAtoms.length === 2) {
        const [atom1, atom2] = tempPairAtoms;
        const dx = atom1.x - atom2.x;
        const dy = atom1.y - atom2.y;
        const dz = atom1.z - atom2.z;
        const distance = Math.sqrt(dx*dx + dy*dy + dz*dz);
        distancePairs.push({atom1, atom2, distance});
        updatePairList();
        updateURL();
        drawDistancePairs();
        isAddingPairInNGL = false;
        tempPairAtoms = [];
        document.getElementById('addPairNGLButton').textContent = 'Add Pair in NGL';
    }
}

// Add event listener for the Add Pair button
document.getElementById('addPairButton').addEventListener('click', function() {
    const atom1Index = document.getElementById('atom1Select').value;
    const atom2Index = document.getElementById('atom2Select').value;
    
    if (atom1Index === '' || atom2Index === '') {
        alert('Please select both atoms for the pair.');
        return;
    }
    
    const atom1 = pickedAtoms[atom1Index];
    const atom2 = pickedAtoms[atom2Index];
    
    const dx = atom1.x - atom2.x;
    const dy = atom1.y - atom2.y;
    const dz = atom1.z - atom2.z;
    const distance = Math.sqrt(dx*dx + dy*dy + dz*dz);
    distancePairs.push({atom1, atom2, distance});
    updatePairList();
    updateURL();
});

// Add event listener for the Add Pair in NGL button
document.getElementById('addPairNGLButton').addEventListener('click', function() {
    isAddingPairInNGL = !isAddingPairInNGL;
    this.textContent = isAddingPairInNGL ? 'Cancel Add Pair' : 'Add Pair in NGL';
    tempPairAtoms = [];
});
