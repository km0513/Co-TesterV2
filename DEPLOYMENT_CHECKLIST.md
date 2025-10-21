# Deployment Checklist - Bug Builder Release

## Pre-Deployment Steps

### 1. Run Database Migration ⚠️ **CRITICAL**

The application will fail to start without this migration!

**Option A: Using run_migration.py (Recommended)**
```bash
# SSH to production server
ssh your-production-server

# Navigate to app directory
cd /path/to/co-tester

# Run migration
python run_migration.py
```

**Option B: Using Flask-Migrate**
```bash
flask db upgrade
```

**Option C: Manual SQL** (See MIGRATION_GUIDE.md)

### 2. Verify Migration Success

```bash
# Check if columns exist
python -c "from app import app, db; from app import BugSession; print([c.name for c in BugSession.__table__.columns])"

# Should see: playwright_script_path, playwright_trace_path, playwright_video_path, playwright_status, playwright_error
```

## Deployment Steps

### 1. Deploy Application Code

```bash
# Trigger Jenkins build or deploy via your CI/CD
# The build should now succeed
```

### 2. Monitor Deployment

```bash
# Watch pod status
kubectl get pods -n dev-prism-app -w

# Check logs
kubectl logs -f deployment/dev-upgrad-co-tester -n dev-prism-app
```

### 3. Verify Application Health

```bash
# Check if pods are running
kubectl get pods -n dev-prism-app | grep upgrad-co-tester

# Should show: Running and Ready 1/1
```

## Post-Deployment Verification

### 1. Test Bug Builder

- [ ] Navigate to https://co-tester.upgrad.dev/bug-builder
- [ ] Click "Start Playwright Browser"
- [ ] Verify browser launches
- [ ] Record some actions
- [ ] Close browser
- [ ] Verify steps are captured
- [ ] Test AI enhancement
- [ ] Test Jira export
- [ ] Test script download
- [ ] Test video recording (if enabled)

### 2. Check Database

```sql
-- Verify new records have Playwright fields
SELECT id, session_id, playwright_status, created_at 
FROM bug_session 
ORDER BY created_at DESC 
LIMIT 5;
```

### 3. Monitor Logs

```bash
# Check for any errors
kubectl logs deployment/dev-upgrad-co-tester -n dev-prism-app --tail=100
```

## Rollback Plan (If Needed)

### If Deployment Fails:

```bash
# Rollback Kubernetes deployment
kubectl rollout undo deployment dev-upgrad-co-tester -n dev-prism-app

# Or rollback to specific revision
kubectl rollout history deployment dev-upgrad-co-tester -n dev-prism-app
kubectl rollout undo deployment dev-upgrad-co-tester -n dev-prism-app --to-revision=26
```

### If Migration Needs Rollback:

```bash
# Using Flask-Migrate
flask db downgrade

# Or manually drop columns (see MIGRATION_GUIDE.md)
```

## Common Issues & Solutions

### Issue: Deployment timeout (like before)
**Cause**: Migration not run
**Solution**: Run migration first, then redeploy

### Issue: "column does not exist" errors
**Cause**: Migration not applied
**Solution**: Run `python run_migration.py`

### Issue: Playwright browser doesn't launch
**Cause**: Playwright not installed or missing dependencies
**Solution**: Check Dockerfile includes Playwright installation

### Issue: Video recording fails
**Cause**: Missing screen recording permissions or dependencies
**Solution**: Check browser permissions and ffmpeg installation

## Success Criteria

✅ All pods are Running (1/1 Ready)
✅ No errors in application logs
✅ Bug builder page loads successfully
✅ Playwright browser launches
✅ Steps are recorded and displayed
✅ AI enhancement works
✅ Jira export creates issues
✅ Script download works
✅ Database has new Playwright fields

## Contacts

- **DevOps**: [Your DevOps Team]
- **Backend**: [Your Backend Team]
- **On-Call**: [On-Call Contact]

## Timeline

- **Migration**: 2-5 minutes
- **Deployment**: 5-10 minutes
- **Verification**: 5 minutes
- **Total**: ~15-20 minutes

---

**Last Updated**: 2025-10-21
**Version**: 1.0.0
**Author**: Development Team
