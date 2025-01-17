from .math_module import xp, _scipy, ensure_np_array, cupy_avail
if cupy_avail:
    import cupy as cp
else:
    cp = False
    
from .imshows import imshow1, imshow2, imshow3

import numpy as np
import scipy
    
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import LogNorm

def pad_or_crop( arr_in, npix ):
    n_arr_in = arr_in.shape[0]
    if n_arr_in == npix:
        return arr_in
    elif npix < n_arr_in:
        x1 = n_arr_in // 2 - npix // 2
        x2 = x1 + npix
        arr_out = arr_in[x1:x2,x1:x2].copy()
    else:
        arr_out = np.zeros((npix,npix), dtype=arr_in.dtype) if isinstance(arr_in, np.ndarray) else cp.zeros((npix,npix), dtype=arr_in.dtype)
        x1 = npix // 2 - n_arr_in // 2
        x2 = x1 + n_arr_in
        arr_out[x1:x2,x1:x2] = arr_in
    return arr_out


def map_acts_to_dm(actuators, dm_mask, Nact=34):
    inds = xp.where(xp.array(dm_mask).flatten().astype(int))[0]
    
    command = xp.zeros((Nact, Nact))
    command.ravel()[inds] = actuators
    
    return command

# Create control matrix
def WeightedLeastSquares(A, weight_map, nprobes=2, rcond=1e-15):
    control_mask = weight_map > 0
    w = weight_map[control_mask]
    for i in range(nprobes-1):
        w = xp.concatenate((w, weight_map[control_mask]))
    W = xp.diag(w)
    cov = A.T.dot(W.dot(A))
    return xp.linalg.inv(cov + rcond * xp.diag(cov).max() * xp.eye(A.shape[1])).dot( A.T.dot(W) )

def TikhonovInverse(A, rcond=1e-15):
    U, s, Vt = xp.linalg.svd(A, full_matrices=False)
    s_inv = s/(s**2 + (rcond * s.max())**2)
    return (Vt.T * s_inv).dot(U.T)

def beta_reg(S, beta=-1):
    # This follows from equations 4 and 5 of the paper of Sidick et al 2017 (SPIE)
    # The gain matrix is derived from the Jacobian (response matrix) but  
    # includes penalty functions introduced that limit actuator combinations

    # The beta value dictates which control modes are penalized, and are indepenent 
    # upon the optical system (coronagraph type etc). This is useful to compare
    # how different optical systems perform (e.g. coronagraph setups).

    # rho indicates the relative actuator strength (meaning which have a 
    # stronger influence on the contrast for a given unit of movement)

    # Alpha^2 = maximum of the rho vector and therefore varies depending upon
    # the opto-mechanical control system being used. It's not particularly
    # meaningful on its own, but is useful for calculating 
    # the Singular mode spectrum defined in section 4.1 (eqn 7) of the paper.

    # S is the sensitivity matrix (aka the Jacobian)
    sts = xp.matmul(S.T, S)  
    rho = xp.diag(sts) # takes diagonal values 
    alpha2 = rho.max() # takes the maximum of the diagonal

    # This is equation 5 of the paper
    gain_matrix = xp.matmul( xp.linalg.inv( sts + alpha2*10.0**(beta)*xp.eye(sts.shape[0]) ), S.T)
    # Actually is the relationship between a poke and the EF in the focal plane.
    return gain_matrix

def create_circ_mask(h, w, center=None, radius=None):

    if center is None: # use the middle of the image
        center = (int(w//2), int(h//2))
    if radius is None: # use the smallest distance between the center and image walls
        radius = min(center[0], center[1], w-center[0], h-center[1])
        
    Y, X = xp.ogrid[:h, :w]
    dist_from_center = xp.sqrt((X - center[0] + 1/2)**2 + (Y - center[1] + 1/2)**2)

    mask = dist_from_center <= radius
    return mask

# Creating focal plane masks
def create_annular_focal_plane_mask(x, y, params, plot=False):
    r = xp.hypot(x, y)
    mask = (r < params['outer_radius']) * (r > params['inner_radius'])
    if 'edge' in params: mask *= (x > params['edge'])
    if 'rotation' in params: mask = _scipy.ndimage.rotate(mask, params['rotation'], reshape=False, order=1)
    if 'x_shift' in params: mask = _scipy.ndimage.shift(mask, (0, params['x_shift']), order=1)
    if 'y_shift' in params: mask = _scipy.ndimage.shift(mask, (params['y_shift'], 0), order=1)
    
    if plot:
        imshow1(mask)
        
    return mask

def create_box_focal_plane_mask(x, y, params):
    xi, yi, xo, yo = (params['xi'], params['yi'], params['xo'], params['yo'])
    mask = xp.array( (x>xi)*(x<xo)*(y>yi)*(y<yo) )
    if 'x_shift' in params: mask = _scipy.ndimage.shift(mask, (0, params['x_shift']), order=1)
    if 'y_shift' in params: mask = _scipy.ndimage.shift(mask, (params['y_shift'], 0), order=1)
    
    return mask > 0

def sms(U, s, alpha2, electric_field, N_DH, 
        Imax_unocc, 
        itr, display=True): 
    '''Calculates the Singular Mode Spectrum.
    This is from section 4 of the Sidick et al 2012 paper (equation 7).
    Note the sum of the sms equals to the normalized intensity.
    '''
     
    # jac: system jacobian
    # electric_field: the electric field acquired by estimation or from the model
    
    E_ri = U.conj().T.dot(electric_field)
    SMS = xp.abs(E_ri)**2/(N_DH/2 * Imax_unocc)
    
    Nbox = 31
    box = xp.ones(Nbox)/Nbox
    SMS_smooth = xp.convolve(SMS, box, mode='same')
    
    x = (s**2/alpha2)
    y = SMS_smooth
    
    xmax = float(np.max(x))
    xmin = 1e-10 
    ymax = 1
    ymin = 1e-14
    
    fig = plt.figure(dpi=125, figsize=(6,4))
    plt.loglog(ensure_np_array(x), ensure_np_array(y))
    plt.title('Singular Mode Spectrum: Iteration {:d}'.format(itr))
    plt.xlim(xmin, xmax)
    plt.ylim(ymin, ymax)
    plt.xlabel(r'$(s_{i}/\alpha)^2$: Square of Normalized Singular Values')
    plt.ylabel('SMS')
    plt.grid()
    plt.close()
    if display:
        display(fig)
    
    return fig


def masked_rms(image,mask=None):
    return np.sqrt(np.mean(image[mask]**2))

def get_random_probes(rms, alpha, dm_mask, fmin=1, fmax=17, nprobe=3):
    # randomized probes generated by PSD
    shape = dm_mask.shape
    ndm = shape[0]

    allprobes = []
    for n in range(nprobe):
        fx = np.fft.rfftfreq(ndm, d=1.0/ndm)
        fy = np.fft.fftfreq(ndm, d=1.0/ndm)
        fxx, fyy = np.meshgrid(fx, fy)
        fr = np.sqrt(fxx**2 + fyy**2)
        spectrum = ( fr**(alpha/2.0) ).astype(complex)
        spectrum[fr <= fmin] = 0
        spectrum[fr >= fmax] = 0
        cvals = np.random.standard_normal(spectrum.shape) + 1j * np.random.standard_normal(spectrum.shape)
        spectrum *= cvals
        probe = np.fft.irfft2(spectrum)
        probe *= dm_mask * rms / masked_rms(probe, dm_mask)
        allprobes.append(probe.real)
        
    return np.asarray(allprobes)


from scipy.linalg import hadamard
def get_hadamard_modes(dm_mask): 
    Nacts = dm_mask.sum().astype(int)
    np2 = 2**int(np.ceil(np.log2(Nacts)))
    hmodes = hadamard(np2)
    
    had_modes = []

    inds = np.where(dm_mask.flatten().astype(int))
    for hmode in hmodes:
        hmode = hmode[:Nacts]
        mode = np.zeros((dm_mask.shape[0]**2))
        mode[inds] = hmode
        had_modes.append(mode)
    had_modes = np.array(had_modes)
    
    return had_modes

def create_fourier_modes(xfp, mask, Nact=34, use_both=True, circular_mask=True):
    intp = scipy.interpolate.interp2d(xfp, xfp, mask)
    
    # This creates the grid and frequencies
    xs = np.linspace(-0.5, 0.5, Nact) * (Nact-1)
    x, y = np.meshgrid(xs, xs)
    x = x.ravel()
    y = y.ravel()
    
    # Create the fourier frequencies. An odd number of modes is preferred for symmetry reasons.
    if Nact % 2 == 0: 
        fxs = np.fft.fftshift( np.fft.fftfreq(Nact+1) )
    else:
        fxs = np.fft.fftshift( np.fft.fftfreq(Nact) )
        
    fx, fy = np.meshgrid(fxs, fxs)
#     print(fx)
    # Select all Fourier modes of interest based on the dark hole mask and remove the piston mode
    mask2 = intp(fxs * Nact, fxs * Nact) * ( ((fx!=0) + (fy!=0)) > 0 ) > 0
    
    fx = fx.ravel()[mask2.ravel()]
    fy = fy.ravel()[mask2.ravel()]
#     print(fx)
    # The modes can rewritten to a single (np.outer(x, fx) + np.outer(y, fy))
    if use_both:
        M1 = [np.cos(2 * np.pi * (fi[0] * x + fi[1] * y)) for fi in zip(fx, fy)]
        M2 = [np.sin(2 * np.pi * (fi[0] * x + fi[1] * y)) for fi in zip(fx, fy)]
        
        # Normalize the modes
        M = np.array(M1+M2)
    else:
        M = np.array([np.sin(2 * np.pi * (fi[0] * x + fi[1] * y)) for fi in zip(fx, fy)])
        
    if circular_mask: 
        circ = np.ones((Nact,Nact))
        r = np.sqrt(x.reshape((Nact,Nact))**2 + y.reshape((Nact,Nact))**2)
        circ[r>(Nact+1)/2] = 0
        M[:] *= circ.flatten()
        
    M /= np.std(M, axis=1, keepdims=True)
        
    return M, fx, fy

def select_fourier_modes(sysi, control_mask, fourier_sampling=0.75, use='both'):
    xfp = (np.linspace(-sysi.npsf/2, sysi.npsf/2-1, sysi.npsf) + 1/2) * sysi.psf_pixelscale_lamD
    fpx, fpy = np.meshgrid(xfp,xfp)
    
    intp = scipy.interpolate.interp2d(xfp, xfp, ensure_np_array(control_mask)) # setup the interpolation function
    
    xpp = np.linspace(-sysi.Nact/2, sysi.Nact/2-1, sysi.Nact) + 1/2
    ppx, ppy = np.meshgrid(xpp,xpp)
    
    fourier_lim = fourier_sampling * int(np.round(xfp.max()/fourier_sampling))
    xfourier = np.arange(-fourier_lim-fourier_sampling/2, fourier_lim+fourier_sampling, fourier_sampling)
    fourier_x, fourier_y = np.meshgrid(xfourier, xfourier) 
    
    # Select the x,y frequencies for the Fourier modes to calibrate the dark hole region
    fourier_grid_mask = ( (intp(xfourier, xfourier) * (((fourier_x!=0) + (fourier_y!=0)) > 0)) > 0 )
    
    fxs = fourier_x.ravel()[fourier_grid_mask.ravel()]
    fys = fourier_y.ravel()[fourier_grid_mask.ravel()]
    sampled_fs = np.vstack((fxs, fys)).T
    
    cos_modes = []
    sin_modes = []
    for f in sampled_fs:
        fx = f[0]/sysi.Nact
        fy = f[1]/sysi.Nact
        cos_modes.append( ( np.cos(2 * np.pi * (fx * ppx + fy * ppy)) * sysi.dm_mask ).flatten() ) 
        sin_modes.append( ( np.sin(2 * np.pi * (fx * ppx + fy * ppy)) * sysi.dm_mask ).flatten() )
    if use=='both' or use=='b':
        modes = cos_modes + sin_modes
    elif use=='cos' or use=='c':
        modes = cos_modes
    elif use=='sin' or use=='s':
        modes = sin_modes
        
    return np.array(modes), sampled_fs

def create_fourier_probes(fourier_modes, Nact=48, plot=False): 
    # make 2 probe modes from the sum of the cos and sin fourier modes
    nfs = fourier_modes.shape[0]//2
    probe1 = fourier_modes[:nfs].sum(axis=0).reshape(Nact,Nact)
    probe2 = fourier_modes[nfs:].sum(axis=0).reshape(Nact,Nact)

    probe1 /= probe1.max()
    probe2 /= probe2.max()

    if plot: 
        imshow2(probe1, probe2)
    probe_modes = np.array([probe1,probe2])

    return probe_modes

def fourier_mode(lambdaD_yx, rms=1, acts_per_D_yx=(34,34), Nact=34, phase=0):
    '''
    Allow linear combinations of sin/cos to rotate through the complex space
    * phase = 0 -> pure cos
    * phase = np.pi/4 -> sqrt(2) [cos + sin]
    * phase = np.pi/2 -> pure sin
    etc.
    '''
    idy, idx = np.indices((Nact, Nact)) - (34-1)/2.
    
    #cfactor = np.cos(phase)
    #sfactor = np.sin(phase)
    prefactor = rms * np.sqrt(2)
    arg = 2*np.pi*(lambdaD_yx[0]/acts_per_D_yx[0]*idy + lambdaD_yx[1]/acts_per_D_yx[1]*idx)
    
    return prefactor * np.cos(arg + phase)

def create_probe_poke_modes(Nact, 
                            poke_indices,
                            plot=False):
    Nprobes = len(poke_indices)
    probe_modes = np.zeros((Nprobes, Nact, Nact))
    for i in range(Nprobes):
        probe_modes[i, poke_indices[i][1], poke_indices[i][0]] = 1
    if plot:
        fig,ax = plt.subplots(nrows=1, ncols=Nprobes, dpi=125, figsize=(10,4))
        for i in range(Nprobes):
            im = ax[i].imshow(probe_modes[i], cmap='viridis')
            divider = make_axes_locatable(ax[i])
            cax = divider.append_axes("right", size="4%", pad=0.075)
            fig.colorbar(im, cax=cax)
        plt.close()
        display(fig)
        
    return probe_modes
    
def create_sinc_probe(Nacts, amp, probe_radius, probe_phase=0, offset=(0,0), bad_axis='x'):
    print('Generating probe with amplitude={:.3e}, radius={:.1f}, phase={:.3f}, offset=({:.1f},{:.1f}), with discontinuity along '.format(amp, probe_radius, probe_phase, offset[0], offset[1]) + bad_axis + ' axis.')
    
    xacts = np.arange( -(Nacts-1)/2, (Nacts+1)/2 )/Nacts - np.round(offset[0])/Nacts
    yacts = np.arange( -(Nacts-1)/2, (Nacts+1)/2 )/Nacts - np.round(offset[1])/Nacts
    Xacts,Yacts = np.meshgrid(xacts,yacts)
    if bad_axis=='x': 
        fX = 2*probe_radius
        fY = probe_radius
        omegaY = probe_radius/2
        probe_commands = amp * np.sinc(fX*Xacts)*np.sinc(fY*Yacts) * np.cos(2*np.pi*omegaY*Yacts + probe_phase)
    elif bad_axis=='y': 
        fX = probe_radius
        fY = 2*probe_radius
        omegaX = probe_radius/2
        probe_commands = amp * np.sinc(fX*Xacts)*np.sinc(fY*Yacts) * np.cos(2*np.pi*omegaX*Xacts + probe_phase) 
    if probe_phase == 0:
        f = 2*probe_radius
        probe_commands = amp * np.sinc(f*Xacts)*np.sinc(f*Yacts)
    return probe_commands

def create_sinc_probes(Npairs, Nact, dm_mask, probe_amplitude, probe_radius=10, probe_offset=(0,0)):
    
    probe_phases = np.linspace(0, np.pi*(Npairs-1)/Npairs, Npairs)
    
    probes = []
    for i in range(Npairs):
        if i%2==0:
            axis = 'x'
        else:
            axis = 'y'
            
        probe = create_sinc_probe(Nact, probe_amplitude, probe_radius, probe_phases[i], offset=probe_offset, bad_axis=axis)
            
        probes.append(probe*dm_mask)
    
    return np.array(probes)
    
def get_radial_dist(shape, scaleyx=(1.0, 1.0), cenyx=None):
    '''
    Compute the radial separation of each pixel
    from the center of a 2D array, and optionally 
    scale in x and y.
    '''
    indices = np.indices(shape)
    if cenyx is None:
        cenyx = ( (shape[0] - 1) / 2., (shape[1] - 1)  / 2.)
    radial = np.sqrt( (scaleyx[0]*(indices[0] - cenyx[0]))**2 + (scaleyx[1]*(indices[1] - cenyx[1]))**2 )
    return radial

def get_radial_contrast(im, mask, nbins=50, cenyx=None):
    im = ensure_np_array(im)
    mask = ensure_np_array(mask)
    radial = get_radial_dist(im.shape, cenyx=cenyx)
    bins = np.linspace(0, radial.max(), num=nbins, endpoint=True)
    digrad = np.digitize(radial, bins)
    profile = np.asarray([np.mean(im[ (digrad == i) & mask]) for i in np.unique(digrad)])
    return bins, profile
    
def plot_radial_contrast(im, mask, pixelscale, nbins=30, cenyx=None, xlims=None, ylims=None):
    bins, contrast = get_radial_contrast(im, mask, nbins=nbins, cenyx=cenyx)
    r = bins * pixelscale

    fig,ax = plt.subplots(nrows=1, ncols=1, dpi=125, figsize=(6,4))
    ax.semilogy(r,contrast)
    ax.set_xlabel('radial position [$\lambda/D$]')
    ax.set_ylabel('Contrast')
    ax.grid()
    if xlims is not None: ax.set_xlim(xlims[0], xlims[1])
    if ylims is not None: ax.set_ylim(ylims[0], ylims[1])
    plt.close()
    display(fig)
    