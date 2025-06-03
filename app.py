from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, g
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import joinedload # Added for eager loading
from sqlalchemy.exc import IntegrityError
import datetime
import click # For Flask CLI commands

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///cmdb.db'  # Define SQLite DB
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'dev_secret_key_for_flashing' # Replace with a real secret key in production / env var
todos = []  # Simple in-memory store for the to-do list UI
db = SQLAlchemy(app)

# --- Models ---
class ConfigurationItem(db.Model):
    __tablename__ = 'configuration_item' # Explicit table name is good practice
    id = db.Column(db.Integer, primary_key=True)
    ci_name = db.Column(db.String(100), unique=True, nullable=False)
    ci_type = db.Column(db.String(50), nullable=False)  # e.g., Server, Application, Database
    status = db.Column(db.String(50), nullable=False)   # e.g., Active, In Maintenance, Retired
    owner = db.Column(db.String(100), nullable=True)
    ip_location = db.Column(db.String(200), nullable=True) # Could be IP address, physical location, etc.
    description = db.Column(db.Text, nullable=True)
    last_updated = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships (back_populates for bidirectional linking)
    # Defines CIs that this CI is a source for in relationships
    source_relationships = db.relationship(
        'Relationship',
        foreign_keys='Relationship.source_ci_id',
        back_populates='source_ci',
        lazy=True,
        cascade="all, delete-orphan"  # If a CI is deleted, its relationships as a source are deleted
    )
    # Defines CIs that this CI is a target for in relationships
    target_relationships = db.relationship(
        'Relationship',
        foreign_keys='Relationship.target_ci_id',
        back_populates='target_ci',
        lazy=True,
        cascade="all, delete-orphan"  # If a CI is deleted, its relationships as a target are deleted
    )

    def __repr__(self):
        return f'<CI {self.ci_name}>'

class Relationship(db.Model):
    __tablename__ = 'relationship' # Explicit table name
    id = db.Column(db.Integer, primary_key=True)
    source_ci_id = db.Column(db.Integer, db.ForeignKey('configuration_item.id'), nullable=False)
    target_ci_id = db.Column(db.Integer, db.ForeignKey('configuration_item.id'), nullable=False)
    relationship_type = db.Column(db.String(50), nullable=False)  # e.g., "Depends on", "Hosts", "Connected to"

    # Relationships to ConfigurationItem
    source_ci = db.relationship('ConfigurationItem', foreign_keys=[source_ci_id], back_populates='source_relationships')
    target_ci = db.relationship('ConfigurationItem', foreign_keys=[target_ci_id], back_populates='target_relationships')

    # Optional: Prevent a CI from being related to itself with the same ID for source and target.
    # More complex validation (e.g., preventing circular dependencies) would be in application logic.
    __table_args__ = (db.CheckConstraint('source_ci_id != target_ci_id', name='ck_not_self_referential'),)


    def __repr__(self):
        if self.source_ci and self.target_ci:
            return f'<Relationship: {self.source_ci.ci_name} [{self.relationship_type}] {self.target_ci.ci_name}>'
        return f'<Relationship ID: {self.id} (CIs not loaded)>'

# --- Constants for UI ---
CI_TYPE_OPTIONS = sorted(["Server", "Application", "Database", "Network Device", "Cloud Service", "Storage", "Virtual Machine", "Container"])
STATUS_OPTIONS = sorted(["Active", "In Maintenance", "Retired", "Provisioning", "Decommissioned"])
# We already have ALLOWED_RELATIONSHIP_TYPES for API validation. We can reuse it or a subset for UI.
# Making sure it's defined before it's used by UI_RELATIONSHIP_TYPES
_api_allowed_rel_types = ["Depends on", "Hosts", "Connected to", "Runs on", "Provides"] # Assuming this was the content of ALLOWED_RELATIONSHIP_TYPES
UI_RELATIONSHIP_TYPES = sorted(list(set(_api_allowed_rel_types + ["Depends on", "Hosts", "Connected to", "Runs on", "Provides"])))


# --- Context Processors & Before Request ---
@app.before_request
def before_request_func():
    g.current_year = datetime.datetime.utcnow().year
    # For ui_index specific data, it's better to calculate it there or pass it directly.
    # If g.total_cis and g.total_relationships are needed by base.html more globally,
    # they could be calculated here, perhaps only for UI routes.
    # For instance: if request.endpoint and request.endpoint.startswith('ui_'):
    #    try:
    #        g.total_cis = db.session.query(ConfigurationItem.id).count()
    #        g.total_relationships = db.session.query(Relationship.id).count()
    #    except: # DB not ready
    #        g.total_cis = "N/A"
    #        g.total_relationships = "N/A"


# --- Simple To-Do UI Routes ---
@app.route('/')
def index():
    """Display the to-do list."""
    return render_template('index.html', todos=todos)

@app.route('/add', methods=['POST'])
def add_todo():
    """Add a new to-do item and redirect back to the list."""
    todo = request.form.get('todo', '').strip()
    if todo:
        todos.append(todo)
        return redirect(url_for('index'))
    # If empty string, simply re-render without adding
    return render_template('index.html', todos=todos)

@app.route('/remove/<int:todo_id>')
def remove_todo(todo_id):
    """Remove a to-do item by index if it exists."""
    if 0 <= todo_id < len(todos):
        todos.pop(todo_id)
    return redirect(url_for('index'))

# --- Configuration Management UI Routes ---

@app.route('/ui/')
def ui_index():
    try:
        g.total_cis = db.session.query(ConfigurationItem.id).count()
        g.total_relationships = db.session.query(Relationship.id).count()
    except Exception: 
        g.total_cis = "N/A (DB not init?)"
        g.total_relationships = "N/A (DB not init?)"
    return render_template('ui_index.html')

@app.route('/ui/cis')
def list_cis_ui():
    query = ConfigurationItem.query 
    search_name = request.args.get('ci_name')
    filter_type = request.args.get('ci_type')
    filter_status = request.args.get('status')
    filter_owner = request.args.get('owner')

    if search_name:
        query = query.filter(ConfigurationItem.ci_name.ilike(f"%{search_name}%"))
    if filter_type:
        query = query.filter(ConfigurationItem.ci_type == filter_type)
    if filter_status:
        query = query.filter(ConfigurationItem.status == filter_status)
    if filter_owner:
        query = query.filter(ConfigurationItem.owner.ilike(f"%{filter_owner}%"))
    
    cis_data = [] 
    try:
        cis_data = query.order_by(ConfigurationItem.ci_name).all()
    except Exception as e:
        flash(f"Error fetching CIs: {str(e)}", "error")
        
    return render_template('list_cis.html', 
                           cis=cis_data, 
                           ci_type_options=CI_TYPE_OPTIONS, 
                           status_options=STATUS_OPTIONS,
                           request_args=request.args)

@app.route('/ui/ci/add', methods=['GET', 'POST'])
def add_ci_ui():
    if request.method == 'POST':
        ci_name = request.form.get('ci_name')
        ci_type = request.form.get('ci_type')
        status = request.form.get('status')
        owner = request.form.get('owner')
        ip_location = request.form.get('ip_location')
        description = request.form.get('description')

        # Store submitted data to pass back to form in case of error
        submitted_data = {
            'ci_name': ci_name, 'ci_type': ci_type, 'status': status, 
            'owner': owner, 'ip_location': ip_location, 'description': description
        }

        if not ci_name or not ci_type or not status:
            flash('Name, Type, and Status are required fields.', 'error')
            return render_template('add_edit_ci.html', 
                                   ci_type_options=CI_TYPE_OPTIONS, 
                                   status_options=STATUS_OPTIONS,
                                   ci=submitted_data) # Pass back submitted values

        existing_ci = ConfigurationItem.query.filter_by(ci_name=ci_name).first()
        if existing_ci:
            flash(f'CI with name "{ci_name}" already exists.', 'error')
            return render_template('add_edit_ci.html', 
                                   ci_type_options=CI_TYPE_OPTIONS, 
                                   status_options=STATUS_OPTIONS,
                                   ci=submitted_data)
        
        try:
            new_ci = ConfigurationItem(
                ci_name=ci_name, ci_type=ci_type, status=status,
                owner=owner, ip_location=ip_location, description=description
            )
            db.session.add(new_ci)
            db.session.commit()
            flash(f'CI "{new_ci.ci_name}" added successfully!', 'success')
            return redirect(url_for('list_cis_ui')) # Consider redirect to view_ci_ui(ci_id=new_ci.id)
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding CI: {str(e)}', 'error')
            return render_template('add_edit_ci.html', 
                                   ci_type_options=CI_TYPE_OPTIONS, 
                                   status_options=STATUS_OPTIONS,
                                   ci=submitted_data) # Keep data on general error
    
    # GET request
    return render_template('add_edit_ci.html', 
                           ci_type_options=CI_TYPE_OPTIONS, 
                           status_options=STATUS_OPTIONS,
                           ci=None) # ci=None for "Add" mode

@app.route('/ui/ci/<int:ci_id>', methods=['GET'])
def view_ci_ui(ci_id):
    # Eager load relationships and the CIs at the other end of those relationships
    ci = db.session.query(ConfigurationItem).options(
        joinedload(ConfigurationItem.source_relationships).joinedload(Relationship.target_ci),
        joinedload(ConfigurationItem.target_relationships).joinedload(Relationship.source_ci)
    ).get(ci_id)

    if not ci:
        flash(f'Configuration Item with ID {ci_id} not found.', 'error')
        return redirect(url_for('list_cis_ui'))
    
    # The relationships are now accessible via ci.source_relationships and ci.target_relationships
    # No need to query them separately if joinedload worked as expected.
    return render_template('view_ci.html', 
                           ci=ci,
                           source_relationships=ci.source_relationships,
                           target_relationships=ci.target_relationships)


@app.route('/ui/ci/<int:ci_id>/edit', methods=['GET', 'POST'])
def edit_ci_ui(ci_id):
    ci_to_edit = db.session.get(ConfigurationItem, ci_id)
    if not ci_to_edit:
        flash(f'CI with ID {ci_id} not found.', 'error')
        return redirect(url_for('list_cis_ui'))

    if request.method == 'POST':
        new_name = request.form.get('ci_name')
        new_type = request.form.get('ci_type')
        new_status = request.form.get('status')
        new_owner = request.form.get('owner')
        new_ip_location = request.form.get('ip_location')
        new_description = request.form.get('description')

        # Create a dictionary of the current form data to pass back on error
        form_data_on_error = {
            'id': ci_id, # Keep ID for action URL in template
            'ci_name': new_name, 'ci_type': new_type, 'status': new_status,
            'owner': new_owner, 'ip_location': new_ip_location, 'description': new_description
        }

        if not new_name or not new_type or not new_status:
            flash('Name, Type, and Status are required fields.', 'error')
            return render_template('add_edit_ci.html', ci=form_data_on_error, 
                                   ci_type_options=CI_TYPE_OPTIONS, 
                                   status_options=STATUS_OPTIONS)

        if ci_to_edit.ci_name != new_name: # Name has changed
            existing_ci = ConfigurationItem.query.filter(ConfigurationItem.id != ci_id, ConfigurationItem.ci_name == new_name).first()
            if existing_ci:
                flash(f'Another CI with name "{new_name}" already exists.', 'error')
                return render_template('add_edit_ci.html', ci=form_data_on_error, 
                                       ci_type_options=CI_TYPE_OPTIONS, 
                                       status_options=STATUS_OPTIONS)
        
        try:
            ci_to_edit.ci_name = new_name
            ci_to_edit.ci_type = new_type
            ci_to_edit.status = new_status
            ci_to_edit.owner = new_owner
            ci_to_edit.ip_location = new_ip_location
            ci_to_edit.description = new_description
            # last_updated will be handled by onupdate in model
            db.session.commit()
            flash(f'CI "{ci_to_edit.ci_name}" updated successfully!', 'success')
            # Consider redirect to view_ci_ui(ci_id=ci_id)
            return redirect(url_for('list_cis_ui')) 
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating CI: {str(e)}', 'error')
            # Pass current (attempted) values back
            return render_template('add_edit_ci.html', ci=form_data_on_error, 
                                   ci_type_options=CI_TYPE_OPTIONS, 
                                   status_options=STATUS_OPTIONS)
    
    # GET request
    return render_template('add_edit_ci.html', ci=ci_to_edit, 
                           ci_type_options=CI_TYPE_OPTIONS, 
                           status_options=STATUS_OPTIONS)

@app.route('/ui/ci/<int:ci_id>/delete', methods=['POST'])
def delete_ci_ui(ci_id):
    try:
        ci_to_delete = db.session.get(ConfigurationItem, ci_id) 
        if ci_to_delete:
            db.session.delete(ci_to_delete)
            db.session.commit()
            flash(f"Configuration Item '{ci_to_delete.ci_name}' (ID: {ci_id}) deleted successfully.", "success")
        else:
            flash(f"Configuration Item with ID {ci_id} not found for deletion.", "warning")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting CI (ID: {ci_id}): {str(e)}", "error")
    return redirect(url_for('list_cis_ui'))

# --- Relationship UI Routes ---
@app.route('/ui/ci/<int:ci_id>/relationship/add', methods=['GET', 'POST']) # Changed to match template
def add_relationship_ui(ci_id):
    source_ci = db.session.get(ConfigurationItem, ci_id)
    if not source_ci:
        flash(f'Source CI with ID {ci_id} not found.', 'error')
        return redirect(url_for('list_cis_ui'))
    
    # For GET request or if POST fails validation (to be built out more)
    if request.method == 'GET':
        flash(f'Adding relationship FROM "{source_ci.ci_name}". Select target CI and relationship type.', 'info')
        # This page will need a form to select target CI and relationship type
        # For now, redirecting back to view_ci for simplicity in this step
        # return render_template('add_edit_relationship.html', source_ci=source_ci, ...)
    
    # Placeholder for POST logic
    flash(f'Relationship management for CI "{source_ci.ci_name}" is under construction.', 'info')
    return redirect(url_for('view_ci_ui', ci_id=ci_id))

@app.route('/ui/relationship/<int:rel_id>/delete/from_ci/<int:ci_id>', methods=['POST'])
def delete_relationship_ui(rel_id, ci_id): # ci_id is to know where to redirect back
    rel_to_delete = db.session.get(Relationship, rel_id)
    if not rel_to_delete:
        flash(f'Relationship with ID {rel_id} not found.', 'error')
    elif rel_to_delete.source_ci_id != ci_id and rel_to_delete.target_ci_id != ci_id:
        # Basic check to ensure the relationship involves the CI we are viewing,
        # though rel_id should be unique enough.
        flash(f'Relationship {rel_id} does not directly involve CI {ci_id}. Deletion aborted for safety.', 'warning')
    else:
        try:
            # For user feedback, get names before deleting
            source_name = rel_to_delete.source_ci.ci_name
            target_name = rel_to_delete.target_ci.ci_name
            rel_type = rel_to_delete.relationship_type
            
            db.session.delete(rel_to_delete)
            db.session.commit()
            flash(f'Relationship ({source_name} {rel_type} {target_name}) deleted successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error deleting relationship: {str(e)}', 'error')
            
    return redirect(url_for('view_ci_ui', ci_id=ci_id))


# --- Helper Functions ---
def ci_to_dict(ci):
    if not ci:
        return None
    return {
        "id": ci.id,
        "ci_name": ci.ci_name,
        "ci_type": ci.ci_type,
        "status": ci.status,
        "owner": ci.owner,
        "ip_location": ci.ip_location,
        "description": ci.description,
        "last_updated": ci.last_updated.isoformat() if ci.last_updated else None
    }

def relationship_to_dict(rel):
    if not rel:
        return None
    return {
        "id": rel.id,
        "source_ci_id": rel.source_ci_id,
        "source_ci_name": rel.source_ci.ci_name if rel.source_ci else "N/A",
        "target_ci_id": rel.target_ci_id,
        "target_ci_name": rel.target_ci.ci_name if rel.target_ci else "N/A",
        "relationship_type": rel.relationship_type
    }

# Allowed relationship types
ALLOWED_RELATIONSHIP_TYPES = ["Depends on", "Hosts", "Connected to", "Runs on", "Provides"]


# --- API Endpoints for CIs ---

@app.route('/api/ci', methods=['POST'])
def create_ci():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No input data provided"}), 400

    required_fields = ['ci_name', 'ci_type', 'status']
    missing_fields = [field for field in required_fields if field not in data or not data[field]]
    if missing_fields:
        return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

    new_ci = ConfigurationItem(
        ci_name=data['ci_name'],
        ci_type=data['ci_type'],
        status=data['status'],
        owner=data.get('owner'),
        ip_location=data.get('ip_location'),
        description=data.get('description')
    )

    try:
        db.session.add(new_ci)
        db.session.commit()
        return jsonify(ci_to_dict(new_ci)), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": f"Configuration Item with name '{data['ci_name']}' already exists."}), 400
    except Exception as e:
        db.session.rollback()
        # Log the exception e
        return jsonify({"error": "An unexpected error occurred while creating the CI."}), 500

@app.route('/api/ci/<int:ci_id>', methods=['GET'])
def get_ci(ci_id):
    ci = db.session.get(ConfigurationItem, ci_id)
    if ci:
        return jsonify(ci_to_dict(ci)), 200
    else:
        return jsonify({"error": f"Configuration Item with ID {ci_id} not found."}), 404

@app.route('/api/ci/<int:ci_id>', methods=['PUT'])
def update_ci(ci_id):
    ci = db.session.get(ConfigurationItem, ci_id)
    if not ci:
        return jsonify({"error": f"Configuration Item with ID {ci_id} not found."}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "No input data provided"}), 400

    # Update fields if provided in the payload
    if 'ci_name' in data:
        # Check for uniqueness if ci_name is being changed to a new value
        if data['ci_name'] != ci.ci_name:
            existing_ci_with_name = ConfigurationItem.query.filter_by(ci_name=data['ci_name']).first()
            if existing_ci_with_name:
                return jsonify({"error": f"Configuration Item with name '{data['ci_name']}' already exists."}), 400
        ci.ci_name = data['ci_name']
    
    if 'ci_type' in data:
        ci.ci_type = data['ci_type']
    if 'status' in data:
        ci.status = data['status']
    if 'owner' in data: # Use .get() for optional fields to allow setting them to null
        ci.owner = data.get('owner')
    if 'ip_location' in data:
        ci.ip_location = data.get('ip_location')
    if 'description' in data:
        ci.description = data.get('description')

    try:
        db.session.commit()
        return jsonify(ci_to_dict(ci)), 200
    except IntegrityError: # Should be caught by the check above, but as a safeguard
        db.session.rollback()
        return jsonify({"error": f"Update failed due to a naming conflict for '{data.get('ci_name')}'."}), 400
    except Exception as e:
        db.session.rollback()
        # Log the exception e
        return jsonify({"error": "An unexpected error occurred while updating the CI."}), 500

@app.route('/api/ci/<int:ci_id>', methods=['DELETE'])
def delete_ci(ci_id):
    ci = db.session.get(ConfigurationItem, ci_id)
    if not ci:
        return jsonify({"error": f"Configuration Item with ID {ci_id} not found."}), 404

    try:
        db.session.delete(ci)
        db.session.commit()
        # return jsonify({"message": f"Configuration Item with ID {ci_id} deleted successfully."}), 200
        return '', 204 # Standard practice for DELETE success
    except Exception as e:
        db.session.rollback()
        # Log the exception e
        return jsonify({"error": "An unexpected error occurred while deleting the CI."}), 500

@app.route('/api/cis', methods=['GET'])
def get_all_cis():
    query = ConfigurationItem.query

    # Filtering
    ci_type = request.args.get('ci_type')
    if ci_type:
        query = query.filter(ConfigurationItem.ci_type == ci_type)
    
    status = request.args.get('status')
    if status:
        query = query.filter(ConfigurationItem.status == status)

    owner = request.args.get('owner')
    if owner:
        query = query.filter(ConfigurationItem.owner == owner) # Case-sensitive, use .ilike for case-insensitive

    # Searching by name (partial, case-insensitive)
    search_name = request.args.get('ci_name')
    if search_name:
        query = query.filter(ConfigurationItem.ci_name.ilike(f"%{search_name}%"))
    
    try:
        cis = query.all()
        return jsonify([ci_to_dict(ci) for ci in cis]), 200
    except Exception as e:
        # Log the exception e
        return jsonify({"error": "An unexpected error occurred while retrieving CIs."}), 500

# --- API Endpoints for Relationships ---

@app.route('/api/relationship', methods=['POST'])
def create_relationship():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No input data provided"}), 400

    required_fields = ['source_ci_id', 'target_ci_id', 'relationship_type']
    missing_fields = [field for field in required_fields if field not in data] # Allow 0 for IDs
    if missing_fields:
        return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

    source_ci_id = data.get('source_ci_id')
    target_ci_id = data.get('target_ci_id')
    relationship_type = data.get('relationship_type')

    if not all(isinstance(id_val, int) for id_val in [source_ci_id, target_ci_id]):
         return jsonify({"error": "source_ci_id and target_ci_id must be integers."}), 400
    
    if source_ci_id == target_ci_id:
        return jsonify({"error": "Source CI ID and Target CI ID cannot be the same."}), 400

    if relationship_type not in ALLOWED_RELATIONSHIP_TYPES:
        return jsonify({"error": f"Invalid relationship_type. Allowed types are: {', '.join(ALLOWED_RELATIONSHIP_TYPES)}"}), 400

    source_ci = db.session.get(ConfigurationItem, source_ci_id)
    target_ci = db.session.get(ConfigurationItem, target_ci_id)

    if not source_ci:
        return jsonify({"error": f"Source Configuration Item with ID {source_ci_id} not found."}), 404
    if not target_ci:
        return jsonify({"error": f"Target Configuration Item with ID {target_ci_id} not found."}), 404

    # Check for existing identical relationship (optional, depends on business rules)
    # existing_rel = Relationship.query.filter_by(
    #     source_ci_id=source_ci_id,
    #     target_ci_id=target_ci_id,
    #     relationship_type=relationship_type
    # ).first()
    # if existing_rel:
    #     return jsonify({"error": "This exact relationship already exists."}), 400

    new_relationship = Relationship(
        source_ci_id=source_ci_id,
        target_ci_id=target_ci_id,
        relationship_type=relationship_type
    )

    try:
        db.session.add(new_relationship)
        db.session.commit()
        # Eagerly load CIs for the response if not already loaded by accessing them
        # This ensures ci_name is available in relationship_to_dict
        db.session.refresh(new_relationship) # to get IDs and potentially other db-generated values
        # Accessing .source_ci and .target_ci loads them if not already loaded.
        # This is generally fine for a single object response.
        # For lists, consider joinedload options in the query if performance becomes an issue.
        return jsonify(relationship_to_dict(new_relationship)), 201
    except IntegrityError as e: # Catches DB constraint violations (e.g., ck_not_self_referential if app logic missed it)
        db.session.rollback()
        # Check if it's the self-referential constraint
        if 'ck_not_self_referential' in str(e.orig):
             return jsonify({"error": "Database constraint violation: Source CI ID and Target CI ID cannot be the same."}), 400
        return jsonify({"error": "Database integrity error."}), 400 # Or more specific
    except Exception as e:
        db.session.rollback()
        # Log the exception e
        return jsonify({"error": "An unexpected error occurred while creating the relationship."}), 500


@app.route('/api/relationship/<int:rel_id>', methods=['GET'])
def get_relationship(rel_id):
    # Use options for joined loading to efficiently get related CI names
    # relationship = Relationship.query.options(
    #     db.joinedload(Relationship.source_ci),
    #     db.joinedload(Relationship.target_ci)
    # ).get(rel_id)
    # For SQLAlchemy 2.0 style, db.session.get is preferred for PK lookups
    relationship = db.session.get(Relationship, rel_id)

    if relationship:
        # Accessing .source_ci and .target_ci will load them if not already.
        return jsonify(relationship_to_dict(relationship)), 200
    else:
        return jsonify({"error": f"Relationship with ID {rel_id} not found."}), 404


@app.route('/api/relationship/<int:rel_id>', methods=['DELETE'])
def delete_relationship(rel_id):
    relationship = db.session.get(Relationship, rel_id)
    if not relationship:
        return jsonify({"error": f"Relationship with ID {rel_id} not found."}), 404

    try:
        db.session.delete(relationship)
        db.session.commit()
        return '', 204
    except Exception as e:
        db.session.rollback()
        # Log the exception e
        return jsonify({"error": "An unexpected error occurred while deleting the relationship."}), 500


@app.route('/api/ci/<int:ci_id>/relationships', methods=['GET'])
def get_relationships_for_ci(ci_id):
    ci = db.session.get(ConfigurationItem, ci_id)
    if not ci:
        return jsonify({"error": f"Configuration Item with ID {ci_id} not found."}), 404

    direction = request.args.get('direction', 'all').lower()
    
    query = Relationship.query
    # Eager load related CIs to avoid N+1 queries when calling relationship_to_dict
    query = query.options(
        db.joinedload(Relationship.source_ci),
        db.joinedload(Relationship.target_ci)
    )

    if direction == 'source':
        query = query.filter(Relationship.source_ci_id == ci_id)
    elif direction == 'target':
        query = query.filter(Relationship.target_ci_id == ci_id)
    elif direction == 'all':
        query = query.filter(
            (Relationship.source_ci_id == ci_id) | (Relationship.target_ci_id == ci_id)
        )
    else:
        return jsonify({"error": "Invalid direction parameter. Use 'source', 'target', or 'all'."}), 400
    
    try:
        relationships = query.all()
        return jsonify([relationship_to_dict(rel) for rel in relationships]), 200
    except Exception as e:
        # Log the exception e
        return jsonify({"error": "An unexpected error occurred while retrieving relationships."}), 500

# To initialize the database, open a Flask shell and run:
# from app import db, app
# with app.app_context():
#     db.create_all()
# print("Database tables created (if they didn't exist).")


# --- Flask CLI Commands ---
@app.cli.command("init-db")
def init_db_command():
    """Clears existing data and creates new tables."""
    with app.app_context(): # Ensure app context for db operations
        db.drop_all()
        db.create_all()
    click.echo("Initialized the database.")

@app.cli.command("seed-db")
def seed_db_command():
    """Seeds the database with sample data."""
    with app.app_context(): # Ensure app context for db operations
        # Ensure tables are created.
        db.create_all()

        # Check if data already exists to avoid duplicates
        if ConfigurationItem.query.first() is not None:
            click.echo("Database already seeded. To re-seed, run 'flask init-db' first.")
            return

        click.echo("Seeding database...")
        # Sample CIs
        try:
            ci1 = ConfigurationItem(ci_name="WebServer-Prod-01", ci_type="Server", status="Active", owner="InfraTeam", ip_location="10.0.1.10", description="Main production web server")
            ci2 = ConfigurationItem(ci_name="AppServer-Prod-01", ci_type="Server", status="Active", owner="AppTeam", ip_location="10.0.1.11", description="Main application server")
            ci3 = ConfigurationItem(ci_name="CustomerDB-Prod-01", ci_type="Database", status="Active", owner="DBTeam", ip_location="10.0.2.5", description="Primary customer database")
            ci4 = ConfigurationItem(ci_name="BillingApp-Prod", ci_type="Application", status="Active", owner="FinanceAppTeam", description="Handles all customer billing")
            ci5 = ConfigurationItem(ci_name="MainWebsite-Prod", ci_type="Application", status="Active", owner="WebTeam", description="Public facing website")
            ci6 = ConfigurationItem(ci_name="OfficeRouter-HQ", ci_type="Network Device", status="Active", owner="NetOps", ip_location="192.168.1.1", description="Main office router")
            ci7 = ConfigurationItem(ci_name="AuthService-Prod", ci_type="Application", status="Active", owner="SecurityTeam", description="Authentication and Authorization service")


            db.session.add_all([ci1, ci2, ci3, ci4, ci5, ci6, ci7])
            db.session.commit() # Commit CIs to get their IDs

            # Sample Relationships
            # Ensure relationship_type values are in ALLOWED_RELATIONSHIP_TYPES
            rel1 = Relationship(source_ci_id=ci4.id, target_ci_id=ci2.id, relationship_type="Runs on") # BillingApp Runs on AppServer
            rel2 = Relationship(source_ci_id=ci4.id, target_ci_id=ci3.id, relationship_type="Depends on") # BillingApp Depends on CustomerDB
            rel3 = Relationship(source_ci_id=ci5.id, target_ci_id=ci1.id, relationship_type="Runs on") # MainWebsite Runs on WebServer
            rel4 = Relationship(source_ci_id=ci2.id, target_ci_id=ci7.id, relationship_type="Depends on") # AppServer Depends on AuthService
            rel5 = Relationship(source_ci_id=ci1.id, target_ci_id=ci6.id, relationship_type="Connected to") # WebServer connected to Router
            rel6 = Relationship(source_ci_id=ci7.id, target_ci_id=ci3.id, relationship_type="Depends on") # AuthService depends on CustomerDB (for user data)


            db.session.add_all([rel1, rel2, rel3, rel4, rel5, rel6])
            db.session.commit()

            click.echo("Seeded the database with sample CIs and Relationships.")
        except Exception as e:
            db.session.rollback()
            click.echo(f"Error seeding database: {e}")


if __name__ == '__main__':
    # It's better to manage DB creation outside the app.run() for production.
    # For development, you might temporarily uncomment the create_all() block above
    # or use a Flask CLI command.
    # Example of how one might run create_all for dev (ensure it's within app context):
    # with app.app_context():
    #     db.create_all()
    app.run(debug=True)
