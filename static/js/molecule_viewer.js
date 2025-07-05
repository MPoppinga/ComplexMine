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
let isLoadingFromURL = false;
let renderTimeout = null;
let isLoadingMolecule = false;

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
    // Prevent duplicate loads
    if (isLoadingMolecule) {
        console.log('Already loading molecule, skipping duplicate call for:', pdb_id);
        return;
    }
    
    console.log('Loading molecule:', pdb_id);
    isLoadingMolecule = true;
    
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
            console.log(`Total atoms in molecule: ${atomData.length}`);
            if (!atomData || atomData.length === 0) {
                throw new Error('Received empty atom data');
            }
            
            console.time('processAtomData');
            currentAtomData = atomData;
            console.timeEnd('processAtomData');
            
            // Create a shape component for the atoms
            console.time('createNGLShape');
            const shape = new NGL.Shape('atom_points');
            
            // Limit atoms for performance (only render first 5000 atoms)
            const atomsToRender = atomData.slice(0, 5000);
            console.log(`Rendering ${atomsToRender.length} of ${atomData.length} atoms`);
            
            atomsToRender.forEach((atom, index) => {
                const color = getElementColor(atom.element);
                shape.addSphere([atom.x, atom.y, atom.z], color, 0.5, `atom${index}`);
            });
            console.timeEnd('createNGLShape');
            
            // Add the shape component to the stage
            console.time('addToStage');
            const shapeComp = stage.addComponentFromObject(shape);
            shapeComp.addRepresentation('point');
            console.timeEnd('addToStage');
            
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
            // Even if molecule data is not available, try to load state from URL
            // This allows query points to be loaded even if the PDB is not in the database
            loadStateFromURL();
        })
        .finally(() => {
            isLoadingMolecule = false; // Always clear the flag
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
    // This function is now only called when a molecule is successfully loaded
    // The main URL state loading is handled in initializePage() -> loadAvailableMolecules()
    const hash = window.location.hash.slice(1);
    if (hash) {
        try {
            const state = JSON.parse(decodeURIComponent(hash));
            console.log('Loading state from URL (after molecule load):', state);
            
            // Only set the atoms and distance pairs (dropdown is already set)
            if (state.pickedAtoms) {
                pickedAtoms = state.pickedAtoms;
            }
            if (state.distancePairs) {
                distancePairs = state.distancePairs;
            }
            
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
            // Check if we have a URL state that specifies a molecule
            const hash = window.location.hash.slice(1);
            let urlState = null;
            if (hash) {
                try {
                    urlState = JSON.parse(decodeURIComponent(hash));
                } catch (error) {
                    console.error('Error parsing URL state:', error);
                }
            }
            
            // Load the molecule specified in URL state, or first molecule by default
            if (data.length > 0 && isInitialLoad) {
                let moleculeToLoad = data[0].id;
                
                if (urlState && urlState.pdbId) {
                    // Check if the URL molecule is in the current list
                    const urlMolecule = data.find(pdb => pdb.id === urlState.pdbId);
                    if (urlMolecule) {
                        moleculeToLoad = urlState.pdbId;
                        console.log('Loading molecule from URL:', moleculeToLoad);
                    } else {
                        // Search for the specific molecule from URL
                        console.log('Molecule from URL not found, searching for:', urlState.pdbId);
                        fetchPDBIdentifiers(urlState.pdbId);
                        return;
                    }
                } else {
                    console.log('Loading first molecule:', moleculeToLoad);
                }
                
                loadMolecule(moleculeToLoad);
                isInitialLoad = false;
            }
        })
        .catch(error => {
            console.error('Error fetching PDB identifiers:', error);
        });
}

// Create and add the search input to the DOM
function createSearchInput() {
    try {
        const pdbSelect = document.getElementById('pdbSelect');
        if (!pdbSelect) {
            console.error('pdbSelect element not found');
            return;
        }

        // Check if search input already exists
        if (document.getElementById('pdbSearch')) {
            console.log('Search input already exists');
            return;
        }

        const searchInput = document.createElement('input');
        searchInput.type = 'text';
        searchInput.id = 'pdbSearch';
        searchInput.placeholder = 'Search PDB...';

        const pdbSelectContainer = pdbSelect.parentNode;
        pdbSelectContainer.insertBefore(searchInput, pdbSelect);

        // Add event listener for search input
        searchInput.addEventListener('input', function() {
            fetchPDBIdentifiers(this.value);
        });
        
        console.log('Search input created successfully');
    } catch (error) {
        console.error('Error creating search input:', error);
    }
}

// Note: createSearchInput() will be called from initializePage() to ensure DOM is ready
// Note: Initialization is now handled by initializePage() at the bottom of the file
// fetchPDBIdentifiers(); // Removed to prevent duplicate initialization

// Function to set up the pdbSelect event listener
function setupPdbSelectListener() {
    try {
        const pdbSelect = document.getElementById('pdbSelect');
        if (!pdbSelect) {
            console.error('pdbSelect element not found for event listener');
            return;
        }

        pdbSelect.addEventListener('change', function() {
            const pdb_id = this.value;
            console.log('Selection changed, loading molecule:', pdb_id);
            
            // Don't trigger loadMolecule if we're currently loading from URL to avoid infinite loops
            if (!isLoadingFromURL) {
                loadMolecule(pdb_id);
            }
        });
        
        console.log('PDB select listener set up successfully');
    } catch (error) {
        console.error('Error setting up PDB select listener:', error);
    }
}

// Function to set up all event listeners
function setupEventListeners() {
    try {
        // Search button
        const searchButton = document.getElementById('searchButton');
        if (!searchButton) {
            console.error('searchButton element not found');
            return;
        }

        searchButton.addEventListener('click', function() {
            if (distancePairs.length === 0) {
                alert('Please add at least one distance pair before searching.');
                return;
            }
            
            // Prepare search data
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

            // Check if auto-queue checkbox is checked
            const autoQueueCheckbox = document.getElementById('autoQueueCheckbox');
            const autoQueue = autoQueueCheckbox ? autoQueueCheckbox.checked : false;
            
            // Get SQL query first
            fetch('/search', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    selected_pairs: searchData,
                    skip_execution: true,  // Just get the SQL, don't execute
                    auto_queue: autoQueue
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    throw new Error(data.error);
                }
                
                // Open search results in new tab with proper separation
                const sqlQuery = data.sql_query || '';
                const searchParams = new URLSearchParams({
                    query: sqlQuery,
                    data: JSON.stringify(searchData)
                });
                
                // Open in new tab - clean architecture
                window.open(`/search_results.html?${searchParams.toString()}`, '_blank');
            })
            .catch(error => {
                console.error('Error preparing search:', error);
                alert(`Error preparing search: ${error.message}`);
            });
        });

        // Add Pair button
        const addPairButton = document.getElementById('addPairButton');
        if (addPairButton) {
            addPairButton.addEventListener('click', function() {
                const atom1Select = document.getElementById('atom1Select');
                const atom2Select = document.getElementById('atom2Select');
                
                if (!atom1Select || !atom2Select) {
                    alert('Atom selection elements not found.');
                    return;
                }
                
                const atom1Index = atom1Select.value;
                const atom2Index = atom2Select.value;
                
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
        }

        // Add Pair in NGL button
        const addPairNGLButton = document.getElementById('addPairNGLButton');
        if (addPairNGLButton) {
            addPairNGLButton.addEventListener('click', function() {
                isAddingPairInNGL = !isAddingPairInNGL;
                this.textContent = isAddingPairInNGL ? 'Cancel Add Pair' : 'Add Pair in NGL';
                tempPairAtoms = [];
            });
        }
        
        console.log('Event listeners set up successfully');
    } catch (error) {
        console.error('Error setting up event listeners:', error);
    }
}

// === Clean architecture: Search handled in separate page ===
// UI state management functions removed - no longer needed with proper separation

// === Search Results handled in separate page (search_results.html) ===
// All search results functionality moved to proper template for clean architecture

// Timer and loading functions moved to search_results.html template

// Search results display removed - handled in search_results.html

// === Search handled in separate page (search_results.html) ===

// Cache stats display removed - handled in search_results.html

// Results display removed - handled in search_results.html

// Monitoring functions removed - handled in search_results.html

// === Helper Functions for Molecule Viewer ===

// === Search Results JavaScript functionality removed ===
// All search results handling is now in search_results.html template

function updateAtomHighlights() {
    try {
        // If no molecule data available, create shapes from picked atoms directly
        if (!currentAtomData || currentAtomData.length === 0) {
            console.log('No molecule data available, creating shapes from picked atoms');
            let shapeComp = stage.getComponentsByName('atom_points')[0];
            const shape = new NGL.Shape('atom_points');
            
            // Safety check: limit number of atoms to prevent browser freeze
            const atomsToRender = pickedAtoms.slice(0, 10000);
            console.log(`Rendering ${atomsToRender.length} picked atoms`);
            
            // Add spheres for picked atoms using their stored coordinate data
            atomsToRender.forEach((atom, index) => {
                if (atom && typeof atom.x === 'number' && typeof atom.y === 'number' && typeof atom.z === 'number') {
                    const color = getElementColor(atom.element);
                    const adjustedColor = color.map(c => Math.min(c * 1.2, 1)); // Make selected atoms brighter
                    shape.addSphere([atom.x, atom.y, atom.z], adjustedColor, 0.75, `atom${index}`);
                }
            });

            if (shapeComp) {
                shapeComp.setShape(shape);
                shapeComp.removeAllRepresentations();
            } else {
                shapeComp = stage.addComponentFromObject(shape);
            }
            
            shapeComp.addRepresentation('point');
            
            // Debounce render to prevent browser freeze
            if (renderTimeout) clearTimeout(renderTimeout);
            renderTimeout = setTimeout(() => {
                stage.viewer.requestRender();
            }, 100);
            return;
        }
    } catch (error) {
        console.error('Error in updateAtomHighlights (no molecule data branch):', error);
        return;
    }
    
    // Normal case: molecule data is available
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
    
    // Debounce render to prevent browser freeze
    if (renderTimeout) clearTimeout(renderTimeout);
    renderTimeout = setTimeout(() => {
        stage.viewer.requestRender();
    }, 100);
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

// These event listeners are now set up in setupEventListeners() function

// Initialize page and load state from URL on page load
function initializePage() {
    console.log('Initializing page...');
    
    // Create the search input first
    createSearchInput();
    
    // Set up event listeners
    setupPdbSelectListener();
    setupEventListeners();
    
    // Load available molecules first, then handle URL state
    loadAvailableMolecules();
}

// Function to load available molecules into the dropdown
function loadAvailableMolecules() {
    fetch('/get_available_molecules')
        .then(response => response.json())
        .then(molecules => {
            const pdbSelect = document.getElementById('pdbSelect');
            pdbSelect.innerHTML = '<option value="">Select a molecule...</option>';
            molecules.forEach(molecule => {
                const option = document.createElement('option');
                option.value = molecule;
                option.textContent = molecule;
                pdbSelect.appendChild(option);
            });
            
            // After loading molecules, check if URL state contains a PDB ID
            const hash = window.location.hash.slice(1);
            if (hash) {
                try {
                    isLoadingFromURL = true; // Set flag to prevent infinite loops
                    const state = JSON.parse(decodeURIComponent(hash));
                    if (state.pdbId) {
                        // Check if the molecule is in the dropdown
                        const existingOption = Array.from(pdbSelect.options).find(option => option.value === state.pdbId);
                        if (existingOption) {
                            pdbSelect.value = state.pdbId;
                            // loadMolecule will call loadStateFromURL internally, so we don't need to pass the state
                            loadMolecule(state.pdbId);
                        } else {
                            // Add the PDB ID to dropdown and visualize query points
                            console.log('PDB not in database, adding to dropdown and showing query points');
                            const option = document.createElement('option');
                            option.value = state.pdbId;
                            option.textContent = state.pdbId + ' (not in DB)';
                            pdbSelect.appendChild(option);
                            
                            // Set the value (change event is blocked by isLoadingFromURL flag)
                            pdbSelect.value = state.pdbId;
                            
                            // Try to load molecule first, if it fails it will load query state in the catch block
                            loadMolecule(state.pdbId);
                        }
                    }
                } catch (error) {
                    console.error('Error parsing URL state:', error);
                } finally {
                    isLoadingFromURL = false; // Clear flag
                }
            }
        })
        .catch(error => {
            console.error('Error loading available molecules:', error);
        });
}

// Function to load only the query state (atoms and pairs) without molecule data
function loadQueryStateOnly(state) {
    console.log('Loading query state only:', state);
    
    // Safety check: limit the number of atoms to prevent browser crashes
    if (state.pickedAtoms && state.pickedAtoms.length > 10000) {
        console.warn('Too many picked atoms in URL state, limiting to first 10000 to prevent browser freeze');
        state.pickedAtoms = state.pickedAtoms.slice(0, 10000);
    }
    
    if (state.distancePairs && state.distancePairs.length > 5000) {
        console.warn('Too many distance pairs in URL state, limiting to first 5000 to prevent browser freeze');
        state.distancePairs = state.distancePairs.slice(0, 5000);
    }
    
    // Set the atoms and distance pairs
    if (state.pickedAtoms) {
        pickedAtoms = state.pickedAtoms;
        console.log(`Loaded ${pickedAtoms.length} picked atoms from URL`);
    }
    if (state.distancePairs) {
        distancePairs = state.distancePairs;
        console.log(`Loaded ${distancePairs.length} distance pairs from URL`);
    }
    
    // Update UI components with performance monitoring
    try {
        console.time('updateAtomList');
        updateAtomList();
        console.timeEnd('updateAtomList');
        
        console.time('updateAtomHighlights');
        updateAtomHighlights(); // This will handle the case where currentAtomData is empty
        console.timeEnd('updateAtomHighlights');
        
        console.time('updatePairList');
        updatePairList();
        console.timeEnd('updatePairList');
        
        console.time('drawDistancePairs');
        drawDistancePairs();
        console.timeEnd('drawDistancePairs');
        
        // Auto-zoom to show the query points (with delay to avoid conflicts)
        if (pickedAtoms.length > 0) {
            setTimeout(() => {
                try {
                    const bounds = calculateBounds(pickedAtoms);
                    const center = bounds.center;
                    const size = Math.max(bounds.size.x, bounds.size.y, bounds.size.z);
                    stage.animationControls.zoomMove(
                        new NGL.Vector3(center.x, center.y, center.z),
                        size * 2,
                        1000
                    );
                } catch (error) {
                    console.error('Error during auto-zoom:', error);
                }
            }, 500); // Delay zoom to let rendering settle
        }
        console.log('Query state loaded successfully');
    } catch (error) {
        console.error('Error updating UI after loading query state:', error);
    }
}

// Helper function to calculate bounds of atoms
function calculateBounds(atoms) {
    let minX = Infinity, minY = Infinity, minZ = Infinity;
    let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
    
    atoms.forEach(atom => {
        minX = Math.min(minX, atom.x);
        minY = Math.min(minY, atom.y);
        minZ = Math.min(minZ, atom.z);
        maxX = Math.max(maxX, atom.x);
        maxY = Math.max(maxY, atom.y);
        maxZ = Math.max(maxZ, atom.z);
    });
    
    return {
        center: {
            x: (minX + maxX) / 2,
            y: (minY + maxY) / 2,
            z: (minZ + maxZ) / 2
        },
        size: {
            x: maxX - minX,
            y: maxY - minY,
            z: maxZ - minZ
        }
    };
}

// Initialize the page when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    initializePage();
});
